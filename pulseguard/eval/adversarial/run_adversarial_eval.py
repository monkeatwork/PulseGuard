"""Adversarial evaluation (CLAUDE.md, "Adversarial evaluation is
required"): 1-prompt/5-min pacing and an attacker who mimics the target's
own baseline rhythm, evaluated against the industry baselines, trained
Stage A/B, trained Stage C and the full fusion at the persisted operating
point — reusing the frozen Phase 2 harness's
detector interface, never a bespoke one. Recall is reported honestly even
if it drops significantly; no threshold-shopping.

Also re-verifies the anti-DoS invariant (CLAUDE.md, evaluation rule #6)
under this specific adversarial pacing.

Usage:
    python -m eval.adversarial.run_adversarial_eval \
        --events data/generated/events.parquet --seed 42 \
        --stage-b-model services/detection_engine/app/model_registry/stage_b.json \
        --stage-c-model services/detection_engine/app/model_registry/stage_c.pt
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from benchmark.baselines import elastic_rule, splunk_rule
from eval.adversarial.mimicry_attacker import compute_historical_gaps, generate_mimicry_attack
from eval.adversarial.slow_pacing_attacker import generate_slow_pacing_attack
from eval.harness.metrics import compute_confusion
from eval.harness.split import assign_split
from services.detection_engine.app.fusion import normalize_stage_a_score
from services.detection_engine.app.operating_point import load_operating_point
from services.detection_engine.app.stage_a_statistical import STAGE_A_THRESHOLD
from services.detection_engine.app.tune_fusion_weights import compute_point_scores
from services.mitigation.app.controller import UserMitigationState, decide_action

logger = logging.getLogger("pulseguard.eval.adversarial")

N_ADVERSARIAL_USERS_PER_PROFILE = 200


def _raw_events_to_dicts(events) -> list[dict]:
    return [
        {
            "event_type": e.event_type,
            "ts": e.ts,
            "decision": e.decision,
            "decision_latency_ms": e.decision_latency_ms,
            "ingest_ts": e.ts,
            "geo_country": e.geo_country,
            "device_id": e.device_id,
            "user_id": e.user_id,
            "label_attack": e.label_attack,
            "attack_profile": e.attack_profile,
            "burst_id": f"adversarial:{e.attack_profile}:{e.user_id}",
        }
        for e in events
    ]


def generate_adversarial_corpus(base_events_df: pd.DataFrame, seed: int, n_per_profile: int) -> pd.DataFrame:
    """Builds adversarial attack episodes for a sample of TEST-split users,
    using each user's own real historical login gaps for the mimicry
    attacker (drawn from their plain_benign / login_attempt history in the
    base corpus)."""
    login_events = base_events_df[base_events_df["event_type"] == "login_attempt"]
    test_users = sorted(
        u for u in login_events["user_id"].unique() if assign_split(seed, u) == "test"
    )

    rows: list[dict] = []
    rng = np.random.default_rng(seed)

    mimicry_users = test_users[:n_per_profile]
    slow_users = test_users[n_per_profile : 2 * n_per_profile]

    for user_id in mimicry_users:
        user_logins = login_events[login_events["user_id"] == user_id].sort_values("ts")
        if user_logins.empty:
            continue
        last_login = user_logins.iloc[-1]
        historical_gaps = compute_historical_gaps(list(user_logins["ts"]))
        start_ts = last_login["ts"] + timedelta(hours=1)
        events = generate_mimicry_attack(
            rng, user_id, start_ts, last_login["device_id"], last_login["user_agent"],
            last_login["src_ip"], last_login["geo_country"] or "US", historical_gaps,
        )
        rows.extend(_raw_events_to_dicts(events))

    for user_id in slow_users:
        user_logins = login_events[login_events["user_id"] == user_id].sort_values("ts")
        if user_logins.empty:
            continue
        last_login = user_logins.iloc[-1]
        start_ts = last_login["ts"] + timedelta(hours=1)
        events = generate_slow_pacing_attack(
            rng, user_id, start_ts, last_login["device_id"], last_login["user_agent"],
            last_login["src_ip"], last_login["geo_country"] or "US",
        )
        rows.extend(_raw_events_to_dicts(events))

    return pd.DataFrame(rows)


def evaluate_baselines(adversarial_df: pd.DataFrame) -> dict:
    results = {}
    for name, detector in (("splunk", splunk_rule.evaluate_burst), ("elastic", elastic_rule.evaluate_burst)):
        by_profile = {}
        for profile, group in adversarial_df.groupby("attack_profile"):
            preds = []
            for burst_id, burst_group in group.groupby("burst_id"):
                events = burst_group.sort_values("ts").to_dict("records")
                preds.append(detector(events))
            recall = sum(preds) / len(preds) if preds else None
            by_profile[profile] = {"recall": recall, "n": len(preds)}
        results[name] = by_profile
    return results


def evaluate_models(adversarial_df: pd.DataFrame, stage_b_model_path: Path, stage_c_model_path: Path) -> dict:
    """Scores every adversarial episode with the trained stages at the
    PERSISTED operating point (operating_point.json) -- the thresholds the
    deployed system uses, chosen on the validation split, never re-picked
    here. Same unit and rule as every other result: an episode is caught if
    any of its decision points crosses the threshold."""
    point = load_operating_point(stage_b_model_path.parent / "operating_point.json")
    points = compute_point_scores(adversarial_df, stage_b_model_path, stage_c_model_path)
    w = point.weights.normalized()
    points["fused"] = (
        w.weight_a * points["stage_a_raw"].map(normalize_stage_a_score)
        + w.weight_b * points["stage_b_calibrated"]
        + w.weight_c * points["stage_c_proba"]
    )
    points["ab_hit"] = (points["stage_a_raw"] > STAGE_A_THRESHOLD) | (
        points["stage_b_calibrated"] >= point.stage_b_threshold
    )
    points["c_hit"] = points["stage_c_proba"] >= point.stage_c_threshold
    points["fusion_hit"] = points["fused"] >= point.threshold
    episodes = points.groupby("generator_burst_id").agg(
        attack_profile=("attack_profile", "first"),
        ab_hit=("ab_hit", "max"),
        c_hit=("c_hit", "max"),
        fusion_hit=("fusion_hit", "max"),
    )

    out: dict[str, dict] = {"stage_ab": {}, "stage_c": {}, "full_fusion": {}}
    for profile, group in episodes.groupby("attack_profile"):
        for key, col in (("stage_ab", "ab_hit"), ("stage_c", "c_hit"), ("full_fusion", "fusion_hit")):
            out[key][profile] = {"recall": float(group[col].mean()), "n": int(len(group))}
    return out


def verify_anti_dos_under_mimicry(n_prompts: int = 500) -> bool:
    """Re-verifies the anti-DoS invariant (CLAUDE.md, evaluation rule #6)
    specifically under mimicry-style pacing (irregular gaps sampled from a
    realistic distribution, rather than the fixed synthetic pacing
    test_controller.py already covers)."""
    rng = np.random.default_rng(123)
    state = UserMitigationState()
    now_seconds = 0.0
    actions_seen = set()
    for _ in range(n_prompts):
        from datetime import datetime, timezone

        now = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=now_seconds)
        action = decide_action(state, now)
        actions_seen.add(action)
        if action == "step_up_required":
            state.record_failure(now)
        now_seconds += float(rng.uniform(60, 600))  # irregular, mimicry-like gaps
    return "locked" not in actions_seen


def run(
    events_path: Path,
    seed: int,
    stage_b_model_path: Path,
    stage_c_model_path: Path,
    results_dir: Path,
) -> dict:
    base_events_df = pd.read_parquet(events_path)
    adversarial_df = generate_adversarial_corpus(base_events_df, seed, N_ADVERSARIAL_USERS_PER_PROFILE)

    models = (
        evaluate_models(adversarial_df, stage_b_model_path, stage_c_model_path)
        if not adversarial_df.empty
        else {"stage_ab": {}, "stage_c": {}, "full_fusion": {}}
    )
    results = {
        "n_adversarial_episodes": int(adversarial_df["burst_id"].nunique()) if not adversarial_df.empty else 0,
        "unit": "episode (caught if any decision point crosses the persisted operating-point threshold)",
        "baselines": evaluate_baselines(adversarial_df) if not adversarial_df.empty else {},
        **models,
        "anti_dos_invariant_holds_under_mimicry_pacing": verify_anti_dos_under_mimicry(),
    }

    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "adversarial.json").write_text(json.dumps(results, indent=2, default=str))
    logger.info("Adversarial evaluation written to %s", results_dir / "adversarial.json")
    return results


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--stage-b-model", default="services/detection_engine/app/model_registry/stage_b.json")
    parser.add_argument("--stage-c-model", default="services/detection_engine/app/model_registry/stage_c.pt")
    parser.add_argument("--results-dir", default="eval/results")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(Path(args.events), args.seed, Path(args.stage_b_model), Path(args.stage_c_model), Path(args.results_dir))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
