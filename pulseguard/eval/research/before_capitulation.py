"""Detection before capitulation (HANDOFF.md task 2).

An in-band defence is only useful if it fires BEFORE the victim taps
Approve: an alert raised on the approval itself arrives after the attacker
is already in. For every attack episode in the test split this finds

  - the capitulating approval: the episode's first `mfa_decision` = approve
    (absent when the victim held out to the end);
  - each detector's first firing moment, as a position in the episode's
    chronological MFA event stream:
      * PulseGuard and its stages score at every decision point, so they
        fire on the decision event where the score first crosses the
        validation-chosen threshold (the live engine's first alert);
      * the Splunk rule is evaluated on every event prefix and fires on the
        prompt that makes it >9 in 10 minutes;
      * the Elastic rule likewise, which by construction can only fire ON an
        approval (it needs "2 denials followed by a success").

Detected before capitulation = first firing strictly before the approval
event. Prompts until detection = prompts the victim had received when the
detector first fired. Both are reported overall and per attack profile.

Usage:
    python -m eval.research.before_capitulation --out eval/results/before_capitulation.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from statistics import median

import pandas as pd

from benchmark.generator.latency_models import NULL_MODELS, FatigueConfig
from eval.research.corpora import build_events, load_users
from eval.research.stats import wilson
from eval.research.suite import RULES, all_score_columns, prepare, score_points, train_suite

logger = logging.getLogger("pulseguard.eval.research.before_capitulation")

MFA = ("mfa_prompt", "mfa_decision")
REPORTED_MODELS = ("pulseguard", "stage_b", "stage_c", "frequency_only")


def first_rule_firing(events: list[dict], rule) -> int | None:
    """Index of the first event after which `rule` holds on the prefix."""
    for i in range(len(events)):
        if rule(events[: i + 1]):
            return i
    return None


def episode_timeline(events: list[dict]) -> dict:
    decision_idx = [i for i, e in enumerate(events) if e["event_type"] == "mfa_decision"]
    approve = next((i for i in decision_idx if events[i]["decision"] == "approve"), None)
    return {"decision_event_index": decision_idx, "capitulation_index": approve}


def analyse(events_df: pd.DataFrame, points: pd.DataFrame, detectors: list[str]) -> list[dict]:
    test_points = points[(points["split"] == "test") & points["label_attack"]]
    hits = {
        ep: g.sort_values(["session_index", "decision_index"])
        for ep, g in test_points.groupby("generator_burst_id")
    }
    rows = []
    attacks = events_df[events_df["burst_id"].isin(hits.keys()) & events_df["event_type"].isin(MFA)]
    for burst_id, group in attacks.groupby("burst_id"):
        events = group.sort_values("ts").to_dict("records")
        tl = episode_timeline(events)
        prompt_counts = (group.sort_values("ts")["event_type"] == "mfa_prompt").cumsum().tolist()
        ep_points = hits[burst_id]
        if len(ep_points) != len(tl["decision_event_index"]):
            raise RuntimeError(f"{burst_id}: decision points do not line up with decision events")
        row = {
            "episode": burst_id,
            "attack_profile": events[0]["attack_profile"],
            "n_prompts": prompt_counts[-1],
            "capitulation_index": tl["capitulation_index"],
            "prompts_at_capitulation": (
                prompt_counts[tl["capitulation_index"]] if tl["capitulation_index"] is not None else None
            ),
            "prompt_counts": prompt_counts,  # prompts received through each event index
        }
        for det in detectors:
            flags = ep_points[f"hit_{det}"].to_numpy()
            k = next((j for j, f in enumerate(flags) if f), None)
            row[det] = tl["decision_event_index"][k] if k is not None else None
        for name, rule in RULES.items():
            row[name] = first_rule_firing(events, rule)
        rows.append(row)
    return rows


def _detector_stats(rows: list[dict], det: str) -> dict:
    n = len(rows)
    detected = [r for r in rows if r[det] is not None]
    capitulated = [r for r in rows if r["capitulation_index"] is not None]
    before = [r for r in capitulated if r[det] is not None and r[det] < r["capitulation_index"]]
    at_or_after = [r for r in capitulated if r[det] is not None and r[det] >= r["capitulation_index"]]
    held_out = [r for r in rows if r["capitulation_index"] is None]
    prompts = [r["prompt_counts"][r[det]] for r in detected]
    margin = [r["prompts_at_capitulation"] - r["prompt_counts"][r[det]] for r in before]
    return {
        "n_attack_episodes": n,
        "detected_at_all": len(detected) / n if n else None,
        "n_capitulated": len(capitulated),
        "detected_before_capitulation": len(before) / len(capitulated) if capitulated else None,
        "detected_before_capitulation_ci": wilson(len(before), len(capitulated)),
        "detected_only_at_or_after_capitulation": len(at_or_after) / len(capitulated) if capitulated else None,
        "missed_capitulated": (len(capitulated) - len(before) - len(at_or_after)) / len(capitulated) if capitulated else None,
        "median_prompts_until_detection": median(prompts) if prompts else None,
        "median_prompts_to_spare": median(margin) if margin else None,
        "n_held_out_to_the_end": len(held_out),
        "detected_when_victim_held_out": (
            sum(1 for r in held_out if r[det] is not None) / len(held_out) if held_out else None
        ),
    }


def summarize(rows: list[dict], detectors: list[str]) -> dict:
    profiles = sorted({r["attack_profile"] for r in rows})
    return {
        "overall": {d: _detector_stats(rows, d) for d in detectors},
        "by_profile": {
            p: {d: _detector_stats([r for r in rows if r["attack_profile"] == p], d) for d in detectors}
            for p in profiles
        },
    }


def run(events_df: pd.DataFrame, seed: int, gru_epochs: int | None = None) -> dict:
    from services.detection_engine.app.train_stage_c import EPOCHS

    view = prepare(events_df, seed)
    suite = train_suite(view, seed, gru_epochs or EPOCHS)
    points = score_points(suite, view)
    models = [d for d in REPORTED_MODELS if d in all_score_columns(suite)]
    rows = analyse(events_df, points, models)
    detectors = [*RULES, *models]
    out = summarize(rows, detectors)
    out["operating_point"] = suite.describe()
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rba-zip", default="data/raw/rba-dataset.zip")
    parser.add_argument("--scale", type=int, default=50000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--strengths", type=float, nargs="+", default=[1.0])
    parser.add_argument("--fatigue-null", choices=NULL_MODELS, default="legacy",
                        help="legacy + strength 1 is the default corpus (make generate)")
    parser.add_argument("--gru-epochs", type=int, default=None)
    parser.add_argument("--out", default="eval/results/before_capitulation.json")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("pulseguard.detection_engine.train_stage_c").setLevel(logging.WARNING)

    users = load_users(Path(args.rba_zip), args.scale)
    results = {}
    for s in args.strengths:
        config = FatigueConfig(strength=s, null_model=args.fatigue_null)
        res = run(build_events(users, args.seed, config), args.seed, args.gru_epochs)
        res["fatigue"] = config.as_dict()
        results[str(s)] = res
        o = res["overall"]
        logger.info(
            "s=%.2f before-capitulation: pulseguard=%.3f (median %s prompts) elastic=%.3f splunk=%.3f",
            s, o["pulseguard"]["detected_before_capitulation"] or 0, o["pulseguard"]["median_prompts_until_detection"],
            o["elastic"]["detected_before_capitulation"] or 0, o["splunk"]["detected_before_capitulation"] or 0,
        )
    out = {
        "seed": args.seed,
        "scale": args.scale,
        "split": "test",
        "definition": (
            "capitulation = the attack episode's first approve decision; detected before capitulation = the "
            "detector's first firing is an earlier event than that approval; prompts until detection = prompts "
            "received when the detector first fired (detected episodes only)"
        ),
        "by_strength": results,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
