"""Grid-searches fusion weights over the VALIDATION split only, then
evaluates the full A+B+C fusion on the frozen test split with those weights
held fixed. This is the guard CLAUDE.md's evaluation rule #1 exists for,
applied to model tuning rather than just the train/test split itself: the
test split's user_ids must never influence which weights get chosen.

The chosen weights and threshold are persisted to
`model_registry/operating_point.json`, which the live scorer loads and
refuses to start without -- so the running system is the evaluated one
(REMEDIATION_TASK.md B2).

Usage:
    python -m services.detection_engine.app.tune_fusion_weights \
        --events data/generated/events.parquet --seed 42 \
        --stage-b-model services/detection_engine/app/model_registry/stage_b.json \
        --stage-c-model services/detection_engine/app/model_registry/stage_c.pt
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from eval.harness.split import assign_split
from services.detection_engine.app.calibration import calibrate, load_calibrator
from services.detection_engine.app.episode_eval import average_precision as _average_precision
from services.detection_engine.app.episode_eval import best_f1_threshold, episode_frame, evaluate, f1_of
from services.detection_engine.app.feature_table import build_feature_table, to_model_matrix
from services.detection_engine.app.fusion import FusionWeights, normalize_stage_a_score
from services.detection_engine.app.operating_point import OperatingPoint, save_operating_point
from services.detection_engine.app.sequence_dataset import build_sequence_dataset
from services.detection_engine.app.stage_a_statistical import stage_a_score
from services.detection_engine.app.stage_b_xgboost import load_model
from services.detection_engine.app.stage_c_gru import StageCGRU
from services.detection_engine.app.train_stage_c import predict_proba as stage_c_predict

logger = logging.getLogger("pulseguard.detection_engine.tune_fusion_weights")

# Searched over the validation split only. 0.05 steps (231 simplex points):
# the previous 0.1 grid plus a "first best wins" rule meant every tie
# resolved toward the LAST stage scanned at the highest weight, which is one
# way a (0, 0, 1) result can be an artifact of the search rather than the
# data (REMEDIATION_TASK.md B3). Ties are now broken by a second,
# threshold-free validation objective -- average precision of the episode
# score -- and only then by grid order.
WEIGHT_STEP = 0.05
WEIGHT_GRID = [round(i * WEIGHT_STEP, 2) for i in range(int(round(1 / WEIGHT_STEP)) + 1)]
F1_TIE_TOLERANCE = 1e-9


def compute_point_scores(events_df: pd.DataFrame, stage_b_model_path: Path, stage_c_model_path: Path) -> pd.DataFrame:
    """One row per decision point: ids, label, and each stage's score.
    `stage_a_norm` is Stage A's raw score mapped onto [0, 1] the way fusion
    uses it."""
    table = build_feature_table(events_df)
    stage_b_model = load_model(stage_b_model_path)
    calibrator = load_calibrator(stage_b_model_path.parent / "stage_b_calibrator.pkl")
    matrix = to_model_matrix(table)

    points = table[["generator_burst_id", "user_id", "label_attack", "attack_profile"]].copy()
    points["stage_a_raw"] = matrix.apply(lambda row: stage_a_score(row.to_dict()), axis=1).to_numpy()
    points["stage_b_calibrated"] = calibrate(calibrator, stage_b_model.predict_proba(matrix)[:, 1])

    X, lengths, _, _, _, seq_burst_ids = build_sequence_dataset(events_df)
    if list(seq_burst_ids) != points["generator_burst_id"].tolist():
        raise RuntimeError("feature-table and sequence rows are misaligned")
    model = StageCGRU()
    model.load_state_dict(torch.load(stage_c_model_path, weights_only=True))
    points["stage_c_proba"] = stage_c_predict(model, X, lengths)
    return points


def _fused(df: pd.DataFrame, weights: FusionWeights) -> np.ndarray:
    w = weights.normalized()
    a = df["stage_a_raw"].map(normalize_stage_a_score).to_numpy()
    return w.weight_a * a + w.weight_b * df["stage_b_calibrated"].to_numpy() + w.weight_c * df["stage_c_proba"].to_numpy()


def _episode_max(df: pd.DataFrame, fused: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """MAX of `fused` per episode (one row = one episode when the frame has
    no generator_burst_id column, e.g. in unit tests)."""
    if "generator_burst_id" not in df.columns:
        return df["label_attack"].to_numpy(dtype=bool), fused
    grouped = pd.DataFrame({"ep": df["generator_burst_id"].to_numpy(), "y": df["label_attack"].to_numpy(), "s": fused})
    agg = grouped.groupby("ep", sort=True).agg(y=("y", "first"), s=("s", "max"))
    return agg["y"].to_numpy(dtype=bool), agg["s"].to_numpy()


def grid_search_weights(val_df: pd.DataFrame) -> FusionWeights:
    """Grid search restricted to `val_df` ONLY -- see module docstring.
    Objective: episode-level F1 at that weight's own best validation
    threshold; ties broken by validation average precision."""
    best_weights, best_key = FusionWeights(), (-1.0, -1.0)
    for wa, wb in itertools.product(WEIGHT_GRID, WEIGHT_GRID):
        wc = round(1.0 - wa - wb, 2)
        if wc < 0:
            continue
        weights = FusionWeights(wa, wb, wc)
        y, s = _episode_max(val_df, _fused(val_df, weights))
        threshold = best_f1_threshold(y, s)
        key = (f1_of(y, s >= threshold), _average_precision(y, s))
        if key[0] > best_key[0] + F1_TIE_TOLERANCE or (abs(key[0] - best_key[0]) <= F1_TIE_TOLERANCE and key[1] > best_key[1]):
            best_key, best_weights = key, weights
    return best_weights


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(events_path: Path, seed: int, stage_b_model_path: Path, stage_c_model_path: Path, results_dir: Path) -> dict:
    events_df = pd.read_parquet(events_path)
    points = compute_point_scores(events_df, stage_b_model_path, stage_c_model_path)
    points["split"] = points["user_id"].apply(lambda u: assign_split(seed, u))

    val_df = points[points["split"] == "val"]
    weights = grid_search_weights(val_df)

    points["fused"] = _fused(points, weights)
    episodes = episode_frame(points, seed, ["fused", "stage_a_raw", "stage_b_calibrated", "stage_c_proba"])
    val_ep = episodes[episodes["split"] == "val"]
    test_ep = episodes[episodes["split"] == "test"]
    threshold = best_f1_threshold(val_ep["label_attack"], val_ep["fused"])

    results = evaluate(test_ep, test_ep["fused"] >= threshold)
    results["weights"] = {"a": weights.weight_a, "b": weights.weight_b, "c": weights.weight_c}
    results["threshold"] = float(threshold)
    results["validation_f1"] = f1_of(val_ep["label_attack"], val_ep["fused"] >= threshold)
    results["weight_grid_step"] = WEIGHT_STEP

    stage_b_threshold = best_f1_threshold(val_ep["label_attack"], val_ep["stage_b_calibrated"])
    stage_c_threshold = best_f1_threshold(val_ep["label_attack"], val_ep["stage_c_proba"])
    save_operating_point(
        OperatingPoint(
            weight_a=weights.weight_a,
            weight_b=weights.weight_b,
            weight_c=weights.weight_c,
            threshold=float(threshold),
            stage_b_threshold=float(stage_b_threshold),
            stage_c_threshold=float(stage_c_threshold),
            seed=seed,
            events_sha256=_sha256(events_path),
            tuned_on="val",
            unit="episode (positive if any decision point crosses the threshold)",
            created_at=datetime.now(timezone.utc).isoformat(),
        ),
        stage_b_model_path.parent / "operating_point.json",
    )

    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "full_fusion.json").write_text(json.dumps(results, indent=2, default=str))
    logger.info(
        "Full fusion (A+B+C): precision=%.3f recall=%.3f fpr=%.3f weights=%s threshold=%.2f (n=%d episodes)",
        results["overall"]["precision"] or 0.0,
        results["overall"]["recall"] or 0.0,
        results["overall"]["fpr"] or 0.0,
        results["weights"],
        threshold,
        results["n_episodes_evaluated"],
    )
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
