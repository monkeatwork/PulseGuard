"""Ablation study (CLAUDE.md, evaluation rule #4): frequency-only vs
frequency+response-behaviour, and with `latency_drift_slope` individually
removed. Reports the result honestly either way — a negative result
reported clearly is worth more than an inflated one (CLAUDE.md). The
`no_measurable_lift_*` flags in the output are computed automatically and
are NOT manually suppressible — see `NO_LIFT_NOISE_FLOOR_PERCENTAGE_POINTS`.

Uses the same session-level decision-point feature table, Stage B model
and episode evaluation rule as the deployed system (`feature_table.py`,
`stage_b_xgboost.py`, `episode_eval.py`), varying only which feature
columns are fed to the model -- this isolates the feature set's own
contribution rather than reflecting any change in model architecture or
evaluation methodology. Excluded columns are removed from the matrix
itself, not merely ignored (test_ablation_variants_are_isolated.py).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

from eval.harness.split import assign_split
from services.detection_engine.app.episode_eval import average_precision as _average_precision
from services.detection_engine.app.episode_eval import best_f1_threshold, episode_frame, evaluate, f1_of
from services.detection_engine.app.feature_table import (
    FEATURE_COLUMNS,
    FREQUENCY_COLUMNS,
    build_feature_table,
    to_model_matrix,
)
from services.detection_engine.app.stage_b_xgboost import train_stage_b

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


def train_and_evaluate_variant(table: pd.DataFrame, columns: list[str], seed: int = 42) -> dict:
    train = table[table["split"] == "train"]
    val = table[table["split"] == "val"]

    X_train, y_train = to_model_matrix(train, columns), train["label_attack"]
    X_val, y_val = to_model_matrix(val, columns), val["label_attack"]

    model = train_stage_b(X_train, y_train, X_val, y_val)
    points = table[["generator_burst_id", "user_id", "label_attack", "attack_profile"]].copy()
    points["score"] = model.predict_proba(to_model_matrix(table, columns))[:, 1]
    episodes = episode_frame(points, seed, ["score"])
    val_ep = episodes[episodes["split"] == "val"]
    test_ep = episodes[episodes["split"] == "test"]

    threshold = best_f1_threshold(val_ep["label_attack"], val_ep["score"])
    result = evaluate(test_ep, test_ep["score"] >= threshold)
    return {
        "overall": result["overall"],
        "f1": f1_of(test_ep["label_attack"], test_ep["score"] >= threshold),
        # threshold-free: can still move when recall saturates at the chosen threshold
        "average_precision": _average_precision(
            test_ep["label_attack"].to_numpy(dtype=bool), test_ep["score"].to_numpy()
        ),
        "by_profile": result["by_profile"],
        "n_episodes_evaluated": result["n_episodes_evaluated"],
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
        results[name] = train_and_evaluate_variant(table, columns, seed)

    freq_recall = results["frequency_only"]["overall"]["recall"] or 0.0
    full_recall = results["frequency_plus_response_behaviour"]["overall"]["recall"] or 0.0
    minus_slope_recall = results["response_behaviour_minus_latency_drift_slope"]["overall"]["recall"] or 0.0

    lift_flags = compute_lift_flags(freq_recall, full_recall, minus_slope_recall)
    response_behaviour_lift_pp = lift_flags["response_behaviour_lift_percentage_points"]
    slope_lift_pp = lift_flags["latency_drift_slope_lift_percentage_points"]

    full, minus = results["frequency_plus_response_behaviour"], results["response_behaviour_minus_latency_drift_slope"]
    freq = results["frequency_only"]
    summary = {
        "seed": seed,
        "noise_floor_percentage_points": NO_LIFT_NOISE_FLOOR_PERCENTAGE_POINTS,
        "variants": results,
        **lift_flags,
        # Supplementary deltas, reported alongside (never instead of) the
        # recall-based lift and its automatic banner: recall can saturate at
        # the operating threshold and hide a difference that shows up in
        # precision/FPR or in the threshold-free average precision.
        "supplementary": {
            "response_behaviour_f1_delta": full["f1"] - freq["f1"],
            "response_behaviour_fpr_delta": (full["overall"]["fpr"] or 0.0) - (freq["overall"]["fpr"] or 0.0),
            "response_behaviour_average_precision_delta": full["average_precision"] - freq["average_precision"],
            "latency_drift_slope_f1_delta": full["f1"] - minus["f1"],
            "latency_drift_slope_fpr_delta": (full["overall"]["fpr"] or 0.0) - (minus["overall"]["fpr"] or 0.0),
            "latency_drift_slope_average_precision_delta": full["average_precision"] - minus["average_precision"],
        },
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
