"""Grid-searches fusion weights over the VALIDATION split only, then
evaluates the full A+B+C fusion on the frozen test split with those weights
held fixed. This is the guard CLAUDE.md's evaluation rule #1 exists for,
applied to model tuning rather than just the train/test split itself: the
test split's user_ids must never influence which weights get chosen.

Usage:
    python -m services.detection_engine.app.tune_fusion_weights \
        --events data/generated/events.parquet --seed 42 \
        --stage-b-model services/detection_engine/app/model_registry/stage_b.json \
        --stage-c-model services/detection_engine/app/model_registry/stage_c.pt
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import sys
from pathlib import Path

import pandas as pd
import torch

from eval.harness.metrics import breakdown_by_profile, compute_confusion
from eval.harness.split import assign_split
from services.detection_engine.app.calibration import calibrate, load_calibrator
from services.detection_engine.app.feature_table import build_feature_table, to_model_matrix
from services.detection_engine.app.fusion import FusionWeights, aggregate_fragment_scores_to_episode, fuse_scores
from services.detection_engine.app.sequence_dataset import build_sequence_dataset
from services.detection_engine.app.stage_a_statistical import stage_a_score
from services.detection_engine.app.stage_b_xgboost import load_model
from services.detection_engine.app.stage_c_gru import StageCGRU
from services.detection_engine.app.train_stage_b import best_f1_threshold

logger = logging.getLogger("pulseguard.detection_engine.tune_fusion_weights")

# Grid searched over the validation split only. Kept coarse (11^2 points,
# third weight implied by normalization) since this is a one-off tuning
# pass, not a hot path.
WEIGHT_GRID = [i / 10 for i in range(0, 11)]


def compute_episode_scores(events_df: pd.DataFrame, seed: int, stage_b_model_path: Path, stage_c_model_path: Path):
    """Returns a DataFrame indexed by episode (generator_burst_id / user_id)
    with columns: user_id, split, label_attack, attack_profile,
    stage_a_raw, stage_b_calibrated, stage_c_proba."""
    feature_table = build_feature_table(events_df)
    stage_b_model = load_model(stage_b_model_path)
    calibrator = load_calibrator(stage_b_model_path.parent / "stage_b_calibrator.pkl")

    matrix = to_model_matrix(feature_table)
    raw_b = stage_b_model.predict_proba(matrix)[:, 1]
    feature_table = feature_table.copy()
    feature_table["stage_b_calibrated"] = calibrate(calibrator, raw_b)
    feature_table["stage_a_raw"] = matrix.apply(lambda row: stage_a_score(row.to_dict()), axis=1)

    episode_a = aggregate_fragment_scores_to_episode(feature_table, "generator_burst_id", "stage_a_raw")
    episode_b = aggregate_fragment_scores_to_episode(feature_table, "generator_burst_id", "stage_b_calibrated")

    episode_meta = (
        feature_table.groupby("generator_burst_id")
        .agg(user_id=("user_id", "first"), label_attack=("label_attack", "first"), attack_profile=("attack_profile", "first"))
        .reset_index()
    )

    X, lengths, y, seq_user_ids, seq_profiles, seq_burst_ids = build_sequence_dataset(events_df)
    stage_c_model = StageCGRU()
    stage_c_model.load_state_dict(torch.load(stage_c_model_path))
    stage_c_model.eval()
    with torch.no_grad():
        stage_c_logits = stage_c_model(torch.tensor(X, dtype=torch.float32), torch.tensor(lengths, dtype=torch.long))
    stage_c_proba = torch.sigmoid(stage_c_logits).numpy()

    seq_df = pd.DataFrame({"generator_burst_id": seq_burst_ids, "stage_c_proba": stage_c_proba})

    episode_meta["stage_a_raw"] = episode_meta["generator_burst_id"].map(episode_a)
    episode_meta["stage_b_calibrated"] = episode_meta["generator_burst_id"].map(episode_b)
    episode_meta = episode_meta.merge(seq_df, on="generator_burst_id", how="left")
    episode_meta["split"] = episode_meta["user_id"].apply(lambda u: assign_split(seed, u))

    return episode_meta


def grid_search_weights(val_df: pd.DataFrame) -> FusionWeights:
    """Grid search restricted to `val_df` ONLY -- see module docstring."""
    best_weights, best_f1 = FusionWeights(), -1.0
    for wa, wb in itertools.product(WEIGHT_GRID, WEIGHT_GRID):
        wc = 1.0 - wa - wb
        if wc < 0:
            continue
        weights = FusionWeights(wa, wb, wc)
        fused = val_df.apply(
            lambda r: fuse_scores(r["stage_a_raw"], r["stage_b_calibrated"], r["stage_c_proba"], weights), axis=1
        )
        threshold = best_f1_threshold(val_df["label_attack"].to_numpy(), fused.to_numpy())
        preds = fused >= threshold
        confusion = compute_confusion(val_df["label_attack"].tolist(), preds.tolist())
        precision, recall = confusion.precision or 0.0, confusion.recall or 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        if f1 > best_f1:
            best_f1, best_weights = f1, weights
    return best_weights


def run(events_path: Path, seed: int, stage_b_model_path: Path, stage_c_model_path: Path, results_dir: Path) -> dict:
    events_df = pd.read_parquet(events_path)
    episode_scores = compute_episode_scores(events_df, seed, stage_b_model_path, stage_c_model_path)

    val_df = episode_scores[episode_scores["split"] == "val"]
    test_df = episode_scores[episode_scores["split"] == "test"]

    weights = grid_search_weights(val_df)

    val_fused = val_df.apply(
        lambda r: fuse_scores(r["stage_a_raw"], r["stage_b_calibrated"], r["stage_c_proba"], weights), axis=1
    )
    threshold = best_f1_threshold(val_df["label_attack"].to_numpy(), val_fused.to_numpy())

    test_fused = test_df.apply(
        lambda r: fuse_scores(r["stage_a_raw"], r["stage_b_calibrated"], r["stage_c_proba"], weights), axis=1
    )
    test_preds = test_fused >= threshold

    rows = [
        {"attack_profile": p, "y_true": bool(t), "y_pred": bool(pred)}
        for p, t, pred in zip(test_df["attack_profile"], test_df["label_attack"], test_preds)
    ]
    confusion = compute_confusion([r["y_true"] for r in rows], [r["y_pred"] for r in rows])
    breakdown = breakdown_by_profile(rows)

    results = {
        "split": "test",
        "n_episodes_evaluated": len(rows),
        "weights": {"a": weights.weight_a, "b": weights.weight_b, "c": weights.weight_c},
        "threshold": float(threshold),
        "overall": confusion.as_dict(),
        "by_profile": breakdown,
    }

    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "full_fusion.json").write_text(json.dumps(results, indent=2, default=str))
    logger.info(
        "Full fusion (A+B+C): precision=%.3f recall=%.3f fpr=%.3f weights=%s (n=%d)",
        results["overall"]["precision"] or 0.0,
        results["overall"]["recall"] or 0.0,
        results["overall"]["fpr"] or 0.0,
        results["weights"],
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
