"""Trains Stage C (GRU) on session-prefix event sequences (one per decision
point, sequence_dataset.py) and evaluates on the frozen test split at
episode granularity -- the same unit as the industry baselines and Stage
A/B, and the same rule the live path alerts on (episode_eval.py).

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

from eval.harness.split import assign_split
from services.detection_engine.app.episode_eval import best_f1_threshold, episode_frame, evaluate
from services.detection_engine.app.sequence_dataset import build_sequence_dataset
from services.detection_engine.app.stage_c_gru import StageCGRU
from services.detection_engine.app.stage_c_numpy import export_state_dict

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


def predict_proba(model: StageCGRU, X: np.ndarray, lengths: np.ndarray, batch_size: int = 4096) -> np.ndarray:
    model.eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(X), batch_size):
            X_t = torch.tensor(X[i : i + batch_size], dtype=torch.float32)
            len_t = torch.tensor(lengths[i : i + batch_size], dtype=torch.long)
            out.append(torch.sigmoid(model(X_t, len_t)).numpy())
    return np.concatenate(out) if out else np.zeros((0,), dtype=np.float32)


def run(events_path: Path, seed: int, model_out: Path, results_dir: Path) -> dict:
    """Trains on TRAIN-split decision-point sequences, picks the threshold
    on VAL-split episodes, reports on TEST-split episodes."""
    torch.manual_seed(seed)
    events_df = pd.read_parquet(events_path)
    X, lengths, y, user_ids, profiles, burst_ids = build_sequence_dataset(events_df)
    splits = np.array([assign_split(seed, u) for u in user_ids])
    train_mask, val_mask = splits == "train", splits == "val"

    model = train_stage_c(
        X[train_mask], lengths[train_mask], y[train_mask],
        X[val_mask], lengths[val_mask], y[val_mask],
    )

    points = pd.DataFrame({
        "generator_burst_id": burst_ids,
        "user_id": user_ids,
        "label_attack": y,
        "attack_profile": profiles,
        "stage_c_proba": predict_proba(model, X, lengths),
    })
    episodes = episode_frame(points, seed, ["stage_c_proba"])
    val_ep = episodes[episodes["split"] == "val"]
    test_ep = episodes[episodes["split"] == "test"]

    threshold = best_f1_threshold(val_ep["label_attack"], val_ep["stage_c_proba"])
    results = evaluate(test_ep, test_ep["stage_c_proba"] >= threshold)
    results["threshold"] = float(threshold)

    model_out.parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), model_out)
    # The live scorer runs the GRU in NumPy (stage_c_numpy.py) and reads this.
    export_state_dict(model.state_dict(), model_out.with_suffix(".npz"))

    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "stage_c.json").write_text(json.dumps(results, indent=2, default=str))
    logger.info(
        "Stage C: precision=%.3f recall=%.3f fpr=%.3f (n=%d episodes)",
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
