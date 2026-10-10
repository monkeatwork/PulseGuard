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

from eval.harness.metrics import breakdown_by_profile, compute_confusion
from eval.harness.split import assign_split
from services.detection_engine.app.calibration import calibrate, fit_calibrator, save_calibrator
from services.detection_engine.app.feature_table import build_feature_table, to_model_matrix
from services.detection_engine.app.stage_a_statistical import STAGE_A_THRESHOLD, stage_a_score
from services.detection_engine.app.stage_b_xgboost import save_model, train_stage_b

logger = logging.getLogger("pulseguard.detection_engine.train_stage_b")

# Threshold on Stage B's calibrated probability that maximizes F1 on the
# validation split is computed at train time, not hardcoded -- see
# DECISIONS.md, "Threshold placement".
DEFAULT_THRESHOLD_GRID = [i / 100 for i in range(1, 100)]


def best_f1_threshold(y_true, calibrated_scores) -> float:
    best_threshold, best_f1 = 0.5, -1.0
    for t in DEFAULT_THRESHOLD_GRID:
        preds = calibrated_scores >= t
        confusion = compute_confusion(list(y_true), list(preds))
        precision = confusion.precision or 0.0
        recall = confusion.recall or 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        if f1 > best_f1:
            best_f1, best_threshold = f1, t
    return best_threshold


def run(events_path: Path, seed: int, model_out: Path, results_dir: Path) -> dict:
    events_df = pd.read_parquet(events_path)
    table = build_feature_table(events_df)
    table["split"] = table["user_id"].apply(lambda u: assign_split(seed, u))

    train_table = table[table["split"] == "train"]
    val_table = table[table["split"] == "val"]
    test_table = table[table["split"] == "test"]

    X_train, y_train = to_model_matrix(train_table), train_table["label_attack"]
    X_val, y_val = to_model_matrix(val_table), val_table["label_attack"]
    X_test, y_test = to_model_matrix(test_table), test_table["label_attack"]

    model = train_stage_b(X_train, y_train, X_val, y_val)
    raw_val_scores = model.predict_proba(X_val)[:, 1]
    calibrator = fit_calibrator(raw_val_scores, y_val.to_numpy())

    raw_test_scores = model.predict_proba(X_test)[:, 1]
    calibrated_test_scores = calibrate(calibrator, raw_test_scores)

    threshold = best_f1_threshold(y_val.to_numpy(), calibrate(calibrator, raw_val_scores))
    stage_b_preds = calibrated_test_scores >= threshold

    stage_a_scores = X_test.apply(lambda row: stage_a_score(row.to_dict()), axis=1)
    stage_a_preds = stage_a_scores > STAGE_A_THRESHOLD

    fused_preds = stage_a_preds | stage_b_preds  # Stage A+B "fused so far" per the plan

    rows = [
        {"attack_profile": profile, "y_true": bool(t), "y_pred": bool(p)}
        for profile, t, p in zip(test_table["attack_profile"], y_test, fused_preds)
    ]
    confusion = compute_confusion([r["y_true"] for r in rows], [r["y_pred"] for r in rows])
    breakdown = breakdown_by_profile(rows)

    results = {
        "split": "test",
        "n_bursts_evaluated": len(rows),
        "threshold": threshold,
        "overall": confusion.as_dict(),
        "by_profile": breakdown,
    }

    model_out.parent.mkdir(parents=True, exist_ok=True)
    save_model(model, model_out)
    save_calibrator(calibrator, model_out.parent / "stage_b_calibrator.pkl")

    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "stage_ab.json").write_text(json.dumps(results, indent=2, default=str))
    logger.info(
        "Stage A+B: precision=%.3f recall=%.3f fpr=%.3f (n=%d)",
        results["overall"]["precision"] or 0.0,
        results["overall"]["recall"] or 0.0,
        results["overall"]["fpr"] or 0.0,
        results["n_bursts_evaluated"],
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
