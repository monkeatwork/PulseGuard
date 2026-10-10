"""Frozen evaluation harness (Phase 2). Every later phase — Stage A/B, Stage
C fusion, the ablation study — reuses `run_detector` unmodified; only the
`detector` callable passed in changes. This is what makes every reported
number comparable to the industry-baseline numbers computed here first.

Evaluation unit: one burst (`burst_id`), which is either an attack profile's
prompt/decision sequence or a benign-high-activity hard-negative session.
Plain-benign users contribute no MFA events and are correctly excluded —
there is nothing for a push-fatigue rule to fire on.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Callable, Literal, Optional

import pandas as pd

from benchmark.baselines import elastic_rule, splunk_rule
from eval.harness.metrics import breakdown_by_profile, compute_confusion
from eval.harness.split import Split, assign_split

logger = logging.getLogger("pulseguard.eval.run_eval")

Detector = Callable[[list[dict]], bool]


def group_events_by_burst(df: pd.DataFrame) -> dict[str, list[dict]]:
    labelled = df[df["burst_id"].notna()]
    return {
        burst_id: group.sort_values("ts").to_dict("records")
        for burst_id, group in labelled.groupby("burst_id")
    }


def burst_ground_truth(df: pd.DataFrame) -> dict[str, dict]:
    labelled = df[df["burst_id"].notna()]
    meta = {}
    for burst_id, group in labelled.groupby("burst_id"):
        first = group.iloc[0]
        meta[burst_id] = {
            "label_attack": bool(first["label_attack"]),
            "attack_profile": first["attack_profile"] if pd.notna(first["attack_profile"]) else None,
            "user_id": first["user_id"],
        }
    return meta


def run_detector(
    df: pd.DataFrame,
    detector: Detector,
    seed: int,
    split_filter: Optional[Split] = "test",
) -> dict:
    """Evaluates `detector` (a callable: list of a burst's raw event dicts
    -> bool prediction) over every labelled burst in `df`, restricted to
    `split_filter` split of the by-user split (None = evaluate all splits,
    used only for exploratory analysis, never for a reported number)."""
    groups = group_events_by_burst(df)
    meta = burst_ground_truth(df)

    rows = []
    for burst_id, events in groups.items():
        m = meta[burst_id]
        if split_filter is not None and assign_split(seed, m["user_id"]) != split_filter:
            continue
        rows.append(
            {
                "attack_profile": m["attack_profile"],
                "y_true": m["label_attack"],
                "y_pred": detector(events),
            }
        )

    confusion = compute_confusion([r["y_true"] for r in rows], [r["y_pred"] for r in rows])
    breakdown = breakdown_by_profile(rows)
    return {
        "split": split_filter,
        "n_bursts_evaluated": len(rows),
        "overall": confusion.as_dict(),
        "by_profile": breakdown,
    }


BASELINE_DETECTORS: dict[str, Detector] = {
    "splunk": splunk_rule.evaluate_burst,
    "elastic": elastic_rule.evaluate_burst,
}


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", required=True, help="path to events.parquet")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out-dir", default="eval/results")
    parser.add_argument("--split", default="test", choices=["train", "val", "test", "all"])
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    df = pd.read_parquet(args.events)
    split_filter = None if args.split == "all" else args.split
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for name, detector in BASELINE_DETECTORS.items():
        results = run_detector(df, detector, args.seed, split_filter=split_filter)
        out_path = out_dir / f"baseline_{name}.json"
        out_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
        logger.info(
            "%s baseline: precision=%.3f recall=%.3f fpr=%.3f (n=%d) -> %s",
            name,
            results["overall"]["precision"] or 0.0,
            results["overall"]["recall"] or 0.0,
            results["overall"]["fpr"] or 0.0,
            results["n_bursts_evaluated"],
            out_path,
        )
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
