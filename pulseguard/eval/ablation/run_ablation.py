"""Ablation study (CLAUDE.md, evaluation rule #4): frequency-only vs
frequency+response-behaviour, and with `latency_drift_slope` individually
removed. Reports the result honestly either way — a negative result
reported clearly is worth more than an inflated one (CLAUDE.md). The
`no_measurable_lift_*` flags in the output are computed automatically and
are NOT manually suppressible — see `NO_LIFT_NOISE_FLOOR_PERCENTAGE_POINTS`.

Uses the same fragment-level feature table and Stage B training/evaluation
machinery as Phase 4 (`feature_table.py`, `stage_b_xgboost.py`), varying
only which feature columns are fed to the model — this isolates the
feature set's own contribution rather than reflecting any change in model
architecture or evaluation methodology.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

from eval.harness.metrics import breakdown_by_profile, compute_confusion
from eval.harness.split import assign_split
from services.detection_engine.app.feature_table import (
    FEATURE_COLUMNS,
    FREQUENCY_COLUMNS,
    build_feature_table,
    to_model_matrix,
)
from services.detection_engine.app.stage_b_xgboost import train_stage_b
from services.detection_engine.app.train_stage_b import best_f1_threshold

logger = logging.getLogger("pulseguard.eval.ablation")

# A recall difference smaller than this is treated as noise, not a real
# lift -- documented, not tunable per-run, and never manually suppressed.
NO_LIFT_NOISE_FLOOR_PERCENTAGE_POINTS = 2.0

RESPONSE_BEHAVIOUR_ONLY_EXCLUDED = ("latency_drift_slope", "latency_drift_slope_valid")

VARIANTS = {
    "frequency_only": FREQUENCY_COLUMNS,
    "frequency_plus_response_behaviour": FEATURE_COLUMNS,
    "response_behaviour_minus_latency_drift_slope": [
        c for c in FEATURE_COLUMNS if c not in RESPONSE_BEHAVIOUR_ONLY_EXCLUDED
    ],
}


def train_and_evaluate_variant(table: pd.DataFrame, columns: list[str]) -> dict:
    train = table[table["split"] == "train"]
    val = table[table["split"] == "val"]
    test = table[table["split"] == "test"]

    X_train, y_train = to_model_matrix(train, columns), train["label_attack"]
    X_val, y_val = to_model_matrix(val, columns), val["label_attack"]
    X_test, y_test = to_model_matrix(test, columns), test["label_attack"]

    model = train_stage_b(X_train, y_train, X_val, y_val)
    val_proba = model.predict_proba(X_val)[:, 1]
    threshold = best_f1_threshold(y_val.to_numpy(), val_proba)
    test_proba = model.predict_proba(X_test)[:, 1]
    preds = test_proba >= threshold

    rows = [
        {"attack_profile": p, "y_true": bool(t), "y_pred": bool(pr)}
        for p, t, pr in zip(test["attack_profile"], y_test, preds)
    ]
    confusion = compute_confusion([r["y_true"] for r in rows], [r["y_pred"] for r in rows])
    breakdown = breakdown_by_profile(rows)
    return {
        "overall": confusion.as_dict(),
        "by_profile": breakdown,
        "n_features": len(columns),
        "features": columns,
        "threshold": float(threshold),
    }


def compute_lift_flags(
    freq_recall: float,
    full_recall: float,
    minus_slope_recall: float,
    noise_floor_percentage_points: float = NO_LIFT_NOISE_FLOOR_PERCENTAGE_POINTS,
) -> dict:
    """Pure function, directly testable without a training run: given three
    recall numbers, computes the lift in percentage points and the
    automatic (never manually suppressible) no-measurable-lift flags."""
    response_behaviour_lift_pp = (full_recall - freq_recall) * 100
    slope_lift_pp = (full_recall - minus_slope_recall) * 100
    return {
        "response_behaviour_lift_percentage_points": response_behaviour_lift_pp,
        "latency_drift_slope_lift_percentage_points": slope_lift_pp,
        "no_measurable_lift_response_behaviour": abs(response_behaviour_lift_pp)
        < noise_floor_percentage_points,
        "no_measurable_lift_latency_drift_slope": abs(slope_lift_pp) < noise_floor_percentage_points,
    }


def build_ablation_table(events_path: Path, seed: int) -> pd.DataFrame:
    events_df = pd.read_parquet(events_path)
    table = build_feature_table(events_df)
    table["split"] = table["user_id"].apply(lambda u: assign_split(seed, u))
    return table


def run(events_path: Path, seed: int, results_dir: Path) -> dict:
    table = build_ablation_table(events_path, seed)

    results = {}
    for name, columns in VARIANTS.items():
        logger.info("Training ablation variant: %s (%d features)", name, len(columns))
        results[name] = train_and_evaluate_variant(table, columns)

    freq_recall = results["frequency_only"]["overall"]["recall"] or 0.0
    full_recall = results["frequency_plus_response_behaviour"]["overall"]["recall"] or 0.0
    minus_slope_recall = results["response_behaviour_minus_latency_drift_slope"]["overall"]["recall"] or 0.0

    lift_flags = compute_lift_flags(freq_recall, full_recall, minus_slope_recall)
    response_behaviour_lift_pp = lift_flags["response_behaviour_lift_percentage_points"]
    slope_lift_pp = lift_flags["latency_drift_slope_lift_percentage_points"]

    summary = {
        "seed": seed,
        "noise_floor_percentage_points": NO_LIFT_NOISE_FLOOR_PERCENTAGE_POINTS,
        "variants": results,
        **lift_flags,
    }

    if summary["no_measurable_lift_response_behaviour"]:
        logger.warning(
            "NO MEASURABLE LIFT: response-behaviour features did not improve recall "
            "beyond the %.1f-point noise floor.",
            NO_LIFT_NOISE_FLOOR_PERCENTAGE_POINTS,
        )
    if summary["no_measurable_lift_latency_drift_slope"]:
        logger.warning(
            "NO MEASURABLE LIFT: latency_drift_slope did not improve recall "
            "beyond the %.1f-point noise floor.",
            NO_LIFT_NOISE_FLOOR_PERCENTAGE_POINTS,
        )

    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "ablation.json").write_text(json.dumps(summary, indent=2, default=str))
    logger.info(
        "Ablation: frequency_only recall=%.3f, full recall=%.3f, minus-slope recall=%.3f "
        "(response-behaviour lift=%.1fpp, slope lift=%.1fpp)",
        freq_recall,
        full_recall,
        minus_slope_recall,
        response_behaviour_lift_pp,
        slope_lift_pp,
    )
    return summary


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--results-dir", default="eval/results")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(Path(args.events), args.seed, Path(args.results_dir))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
