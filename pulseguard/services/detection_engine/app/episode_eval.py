"""Decision-point scores -> episode predictions, the one place that turns
per-decision model output into the numbers every result file reports.

The rule is the live alerting rule: an episode is predicted positive iff ANY
of its decision points scores at or above the threshold (the live detection
engine raises the alert at the first crossing). Episode score = MAX over its
decision points. Thresholds are chosen on the validation split's EPISODES
(never decision rows, never test users), so the operating point is tuned at
the same granularity it is reported and deployed at.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from eval.harness.metrics import breakdown_by_profile, compute_confusion
from eval.harness.split import assign_split

THRESHOLD_GRID = [i / 100 for i in range(1, 100)]


def f1_of(y_true, y_pred) -> float:
    c = compute_confusion(list(map(bool, y_true)), list(map(bool, y_pred)))
    p, r = c.precision or 0.0, c.recall or 0.0
    return 2 * p * r / (p + r) if (p + r) else 0.0


def best_f1_threshold(y_true, scores, grid=THRESHOLD_GRID) -> float:
    y_true = np.asarray(y_true, dtype=bool)
    scores = np.asarray(scores, dtype=float)
    best_t, best_f1 = 0.5, -1.0
    for t in grid:
        f1 = f1_of(y_true, scores >= t)
        if f1 > best_f1:
            best_f1, best_t = f1, t
    return best_t


def average_precision(y: np.ndarray, s: np.ndarray) -> float:
    """Threshold-free ranking quality of `s` against boolean labels `y`."""
    if y.sum() == 0:
        return 0.0
    order = np.argsort(-s, kind="mergesort")
    y_sorted = y[order]
    tp = np.cumsum(y_sorted)
    precision = tp / np.arange(1, len(y_sorted) + 1)
    return float((precision * y_sorted).sum() / y_sorted.sum())


def episode_frame(points: pd.DataFrame, seed: int, score_cols: list[str]) -> pd.DataFrame:
    """`points` has one row per decision point with columns
    generator_burst_id, user_id, label_attack, attack_profile and the score
    columns. Returns one row per episode with each score column MAX-reduced
    and the by-user split attached."""
    agg = {"user_id": ("user_id", "first"), "label_attack": ("label_attack", "first"),
           "attack_profile": ("attack_profile", "first"), "n_decision_points": ("user_id", "size")}
    for col in score_cols:
        agg[col] = (col, "max")
    episodes = points.groupby("generator_burst_id", sort=True).agg(**agg).reset_index()
    episodes["attack_profile"] = episodes["attack_profile"].where(episodes["attack_profile"].notna(), None)
    episodes["split"] = episodes["user_id"].apply(lambda u: assign_split(seed, u))
    return episodes


def evaluate(episodes: pd.DataFrame, predictions) -> dict:
    rows = [
        {"attack_profile": p, "y_true": bool(t), "y_pred": bool(pred)}
        for p, t, pred in zip(episodes["attack_profile"], episodes["label_attack"], predictions)
    ]
    confusion = compute_confusion([r["y_true"] for r in rows], [r["y_pred"] for r in rows])
    return {
        "split": "test",
        "unit": "episode (positive if any decision point crosses the threshold)",
        "n_episodes_evaluated": len(rows),
        # kept under the historical key too: eval/harness/report.py reads it
        "n_bursts_evaluated": len(rows),
        "overall": confusion.as_dict(),
        "by_profile": breakdown_by_profile(rows),
    }
