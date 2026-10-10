"""Trains Stage B (XGBoost) over the full frequency + response-behaviour
feature vector, calibrates with isotonic regression, and evaluates against
the frozen Phase 2 harness's by-user split — so the numbers are directly
comparable to eval/results/baseline_*.json.

Usage:
    python -m services.detection_engine.app.train_stage_b \
        --events data/generated/events.parquet --seed 42 \
        --model-out services/detection_engine/app/model_registry/stage_b.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

from eval.harness.split import assign_split
from services.detection_engine.app.calibration import calibrate, fit_calibrator, save_calibrator
from services.detection_engine.app.episode_eval import (
    THRESHOLD_GRID as DEFAULT_THRESHOLD_GRID,
    best_f1_threshold,
    episode_frame,
    evaluate,
)
from services.detection_engine.app.feature_table import build_feature_table, to_model_matrix
from services.detection_engine.app.stage_a_statistical import STAGE_A_THRESHOLD, stage_a_score
from services.detection_engine.app.stage_b_xgboost import save_model, train_stage_b

logger = logging.getLogger("pulseguard.detection_engine.train_stage_b")


def run(events_path: Path, seed: int, model_out: Path, results_dir: Path) -> dict:
    """Trains on TRAIN-split decision points, calibrates and picks the
    threshold on VAL-split episodes, reports on TEST-split episodes. Unit and
    rule: see feature_table.py / episode_eval.py."""
    events_df = pd.read_parquet(events_path)
    table = build_feature_table(events_df)
    table["split"] = table["user_id"].apply(lambda u: assign_split(seed, u))

    train_table = table[table["split"] == "train"]
    val_table = table[table["split"] == "val"]

    X_train, y_train = to_model_matrix(train_table), train_table["label_attack"]
    X_val, y_val = to_model_matrix(val_table), val_table["label_attack"]

    model = train_stage_b(X_train, y_train, X_val, y_val)
    calibrator = fit_calibrator(model.predict_proba(X_val)[:, 1], y_val.to_numpy())

    matrix = to_model_matrix(table)
    table = table.copy()
    table["stage_b_calibrated"] = calibrate(calibrator, model.predict_proba(matrix)[:, 1])
    table["stage_a_raw"] = matrix.apply(lambda row: stage_a_score(row.to_dict()), axis=1)
    table["stage_a_flag"] = (table["stage_a_raw"] > STAGE_A_THRESHOLD).astype(float)

    episodes = episode_frame(table, seed, ["stage_b_calibrated", "stage_a_raw", "stage_a_flag"])
    val_ep = episodes[episodes["split"] == "val"]
    test_ep = episodes[episodes["split"] == "test"]

    threshold = best_f1_threshold(val_ep["label_attack"], val_ep["stage_b_calibrated"])
    # Stage A+B "fused so far": positive if either stage fires at any decision point.
    preds = (test_ep["stage_a_flag"] > 0) | (test_ep["stage_b_calibrated"] >= threshold)

    results = evaluate(test_ep, preds)
    results["threshold"] = threshold
    # Reported alongside the historical "A OR B" rule (never instead of it):
    # each half on its own, at the same validation-chosen thresholds, so a
    # reader can see which half any false positive comes from.
    stage_b_only = evaluate(test_ep, test_ep["stage_b_calibrated"] >= threshold)
    stage_a_only = evaluate(test_ep, test_ep["stage_a_flag"] > 0)
    results["stage_b_only"] = {"overall": stage_b_only["overall"], "by_profile": stage_b_only["by_profile"]}
    results["stage_a_only"] = {"overall": stage_a_only["overall"], "by_profile": stage_a_only["by_profile"]}
    results["stage_a_threshold"] = STAGE_A_THRESHOLD
    results["n_decision_points_trained_on"] = int(len(train_table))

    model_out.parent.mkdir(parents=True, exist_ok=True)
    save_model(model, model_out)
    save_calibrator(calibrator, model_out.parent / "stage_b_calibrator.pkl")

    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "stage_ab.json").write_text(json.dumps(results, indent=2, default=str))
    logger.info(
        "Stage A+B: precision=%.3f recall=%.3f fpr=%.3f (n=%d episodes)",
        results["overall"]["precision"] or 0.0,
        results["overall"]["recall"] or 0.0,
        results["overall"]["fpr"] or 0.0,
        results["n_episodes_evaluated"],
    )
    return results


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--model-out", default="services/detection_engine/app/model_registry/stage_b.json")
    parser.add_argument("--results-dir", default="eval/results")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(Path(args.events), args.seed, Path(args.model_out), Path(args.results_dir))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
