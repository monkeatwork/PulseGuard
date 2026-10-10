"""Trains Stage C (GRU) on per-user event sequences and evaluates on the
frozen test split at user-episode granularity — the same unit Phase 2's
industry baselines used, so the comparison is apples-to-apples (unlike
Stage A/B's fragment-level training/evaluation unit; see
sequence_dataset.py's module docstring for why the two stages deliberately
use different granularities).

Usage:
    python -m services.detection_engine.app.train_stage_c \
        --events data/generated/events.parquet --seed 42
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from eval.harness.metrics import breakdown_by_profile, compute_confusion
from eval.harness.split import assign_split
from services.detection_engine.app.sequence_dataset import build_sequence_dataset
from services.detection_engine.app.stage_c_gru import StageCGRU
from services.detection_engine.app.train_stage_b import best_f1_threshold

logger = logging.getLogger("pulseguard.detection_engine.train_stage_c")

EPOCHS = 15
BATCH_SIZE = 64
LEARNING_RATE = 1e-3


def _to_tensors(X: np.ndarray, lengths: np.ndarray, y: np.ndarray):
    return (
        torch.tensor(X, dtype=torch.float32),
        torch.tensor(lengths, dtype=torch.long),
        torch.tensor(y, dtype=torch.float32),
    )


def train_stage_c(
    X_train: np.ndarray, lengths_train: np.ndarray, y_train: np.ndarray,
    X_val: np.ndarray, lengths_val: np.ndarray, y_val: np.ndarray,
    epochs: int = EPOCHS,
) -> StageCGRU:
    model = StageCGRU()
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    loss_fn = nn.BCEWithLogitsLoss()

    X_train_t, len_train_t, y_train_t = _to_tensors(X_train, lengths_train, y_train)
    loader = DataLoader(TensorDataset(X_train_t, len_train_t, y_train_t), batch_size=BATCH_SIZE, shuffle=True)
    X_val_t, len_val_t, y_val_t = _to_tensors(X_val, lengths_val, y_val)

    best_val_loss = float("inf")
    best_state = None
    for epoch in range(epochs):
        model.train()
        for xb, lb, yb in loader:
            optimizer.zero_grad()
            loss = loss_fn(model(xb, lb), yb)
            loss.backward()
            optimizer.step()

        model.eval()
        with torch.no_grad():
            val_loss = loss_fn(model(X_val_t, len_val_t), y_val_t).item()
        logger.info("epoch %d val_loss=%.4f", epoch, val_loss)
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = {k: v.clone() for k, v in model.state_dict().items()}

    if best_state is not None:
        model.load_state_dict(best_state)
    return model


def predict_proba(model: StageCGRU, X: np.ndarray, lengths: np.ndarray) -> np.ndarray:
    model.eval()
    X_t = torch.tensor(X, dtype=torch.float32)
    len_t = torch.tensor(lengths, dtype=torch.long)
    with torch.no_grad():
        logits = model(X_t, len_t)
    return torch.sigmoid(logits).numpy()


def run(events_path: Path, seed: int, model_out: Path, results_dir: Path) -> dict:
    events_df = pd.read_parquet(events_path)
    X, lengths, y, user_ids, profiles, burst_ids = build_sequence_dataset(events_df)
    splits = np.array([assign_split(seed, u) for u in user_ids])

    train_mask, val_mask, test_mask = splits == "train", splits == "val", splits == "test"

    model = train_stage_c(
        X[train_mask], lengths[train_mask], y[train_mask],
        X[val_mask], lengths[val_mask], y[val_mask],
    )

    val_proba = predict_proba(model, X[val_mask], lengths[val_mask])
    threshold = best_f1_threshold(y[val_mask], val_proba)

    test_proba = predict_proba(model, X[test_mask], lengths[test_mask])
    test_preds = test_proba >= threshold
    test_profiles = np.array(profiles, dtype=object)[test_mask]
    test_labels = y[test_mask]

    rows = [
        {"attack_profile": p, "y_true": bool(t), "y_pred": bool(pred)}
        for p, t, pred in zip(test_profiles, test_labels, test_preds)
    ]
    confusion = compute_confusion([r["y_true"] for r in rows], [r["y_pred"] for r in rows])
    breakdown = breakdown_by_profile(rows)

    results = {
        "split": "test",
        "n_episodes_evaluated": len(rows),
        "threshold": float(threshold),
        "overall": confusion.as_dict(),
        "by_profile": breakdown,
    }

    model_out.parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), model_out)

    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "stage_c.json").write_text(json.dumps(results, indent=2, default=str))
    logger.info(
        "Stage C: precision=%.3f recall=%.3f fpr=%.3f (n=%d)",
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
    parser.add_argument("--model-out", default="services/detection_engine/app/model_registry/stage_c.pt")
    parser.add_argument("--results-dir", default="eval/results")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(Path(args.events), args.seed, Path(args.model_out), Path(args.results_dir))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
