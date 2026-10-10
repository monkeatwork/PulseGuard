"""Adversarial evaluation (CLAUDE.md, "Adversarial evaluation is
required"): 1-prompt/5-min pacing and an attacker who mimics the target's
own baseline rhythm, evaluated against the industry baselines, trained
Stage A/B, and trained Stage C — reusing the frozen Phase 2 harness's
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
from services.detection_engine.app.calibration import calibrate, load_calibrator
from services.detection_engine.app.feature_table import build_feature_table, to_model_matrix
from services.detection_engine.app.sequence_dataset import pairs_to_sequence
from services.detection_engine.app.stage_a_statistical import stage_a_flag
from services.detection_engine.app.stage_b_xgboost import load_model
from services.detection_engine.app.stage_c_gru import StageCGRU
from pulseguard_common.windows import pair_prompts_and_decisions
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


def evaluate_stage_ab(adversarial_df: pd.DataFrame, stage_b_model_path: Path) -> dict:
    table = build_feature_table(adversarial_df)
    if table.empty:
        return {}
    model = load_model(stage_b_model_path)
    calibrator = load_calibrator(stage_b_model_path.parent / "stage_b_calibrator.pkl")
    matrix = to_model_matrix(table)
    raw_scores = model.predict_proba(matrix)[:, 1]
    calibrated = calibrate(calibrator, raw_scores)
    stage_a_preds = matrix.apply(lambda row: stage_a_flag(row.to_dict()), axis=1)
    fused_preds = stage_a_preds | (calibrated >= 0.5)

    by_profile = {}
    for profile in table["attack_profile"].dropna().unique():
        mask = table["attack_profile"] == profile
        recall = fused_preds[mask].mean() if mask.any() else None
        by_profile[profile] = {"recall": float(recall) if recall is not None else None, "n": int(mask.sum())}
    return by_profile


def evaluate_stage_c(adversarial_df: pd.DataFrame, stage_c_model_path: Path) -> dict:
    labelled = adversarial_df[adversarial_df["burst_id"].notna()]
    if labelled.empty:
        return {}

    model = StageCGRU()
    model.load_state_dict(torch.load(stage_c_model_path))
    model.eval()

    by_profile: dict[str, list] = {}
    for burst_id, group in labelled.groupby("burst_id"):
        group = group.sort_values("ts")
        profile = group.iloc[0]["attack_profile"]
        pairs = pair_prompts_and_decisions(group.to_dict("records"))
        seq, length = pairs_to_sequence(pairs)
        with torch.no_grad():
            logit = model(
                torch.tensor(seq[None, ...], dtype=torch.float32),
                torch.tensor([length], dtype=torch.long),
            )
        pred = torch.sigmoid(logit).item() >= 0.5
        by_profile.setdefault(profile, []).append(pred)

    return {
        profile: {"recall": sum(preds) / len(preds), "n": len(preds)}
        for profile, preds in by_profile.items()
    }


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

    results = {
        "n_adversarial_episodes": int(adversarial_df["burst_id"].nunique()) if not adversarial_df.empty else 0,
        "baselines": evaluate_baselines(adversarial_df) if not adversarial_df.empty else {},
        "stage_ab": evaluate_stage_ab(adversarial_df, stage_b_model_path) if not adversarial_df.empty else {},
        "stage_c": evaluate_stage_c(adversarial_df, stage_c_model_path) if not adversarial_df.empty else {},
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
