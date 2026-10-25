"""Train-once, score-anywhere wrapper around the deployed detector stages,
for the research experiments (fatigue sweep, train/test strength grid,
detection before capitulation, adaptive attacker, learned baselines).

Nothing here is a new detector or a new evaluation rule. It calls the same
functions the production pipeline (`make train evaluate`) calls --
feature_table / sequence_dataset for inputs, train_stage_b / train_stage_c /
grid_search_weights for models and fusion, episode_eval for the
"any decision point crosses the threshold" rule, and the frozen harness
(eval/harness) for Splunk and Elastic -- but keeps every trained object in
memory so one training run can score several corpora (e.g. train on
fatigue strength 1, test on strength 0.25) without touching
`model_registry/`, which stays the deployed set.

Tuning discipline is the pipeline's: models fit on TRAIN-split users,
calibration, fusion weights and every threshold on VAL-split episodes,
reported numbers on TEST-split episodes only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from benchmark.baselines import elastic_rule, splunk_rule
from eval.harness.run_eval import run_detector
from eval.harness.split import assign_split
from services.detection_engine.app.calibration import calibrate, fit_calibrator
from services.detection_engine.app.episode_eval import best_f1_threshold, episode_frame, evaluate
from services.detection_engine.app.feature_table import (
    FEATURE_COLUMNS,
    FREQUENCY_COLUMNS,
    build_feature_table,
    to_model_matrix,
)
from services.detection_engine.app.fusion import FusionWeights, normalize_stage_a_score
from services.detection_engine.app.sequence_dataset import build_sequence_dataset
from services.detection_engine.app.stage_a_statistical import STAGE_A_THRESHOLD, stage_a_score
from services.detection_engine.app.stage_b_xgboost import train_stage_b
from services.detection_engine.app.train_stage_c import EPOCHS, predict_proba, train_stage_c
from services.detection_engine.app.tune_fusion_weights import grid_search_weights

logger = logging.getLogger("pulseguard.eval.research")

META_COLUMNS = ["generator_burst_id", "user_id", "label_attack", "attack_profile", "session_index", "decision_index"]

# Detector name -> per-decision-point score column. Episode score = MAX.
SCORE_COLUMNS = {
    "stage_a": "stage_a_flag",
    "stage_b": "stage_b",
    "frequency_only": "stage_b_freq",
    "stage_c": "stage_c",
    "pulseguard": "fused",
}

RULES: dict[str, Callable[[list[dict]], bool]] = {
    "splunk": splunk_rule.evaluate_burst,
    "elastic": elastic_rule.evaluate_burst,
}


@dataclass
class CorpusView:
    """One corpus, featurised once: the decision-point feature table and the
    Stage C sequences, row-aligned (both come from iter_decision_points)."""

    events_df: pd.DataFrame
    table: pd.DataFrame
    X_seq: np.ndarray
    seq_lengths: np.ndarray
    seed: int

    @property
    def split(self) -> pd.Series:
        return self.table["split"]


def prepare(events_df: pd.DataFrame, seed: int) -> CorpusView:
    table = build_feature_table(events_df)
    X, lengths, _, _, _, burst_ids = build_sequence_dataset(events_df)
    if list(burst_ids) != table["generator_burst_id"].tolist():
        raise RuntimeError("feature-table and sequence rows are misaligned")
    table["split"] = table["user_id"].apply(lambda u: assign_split(seed, u))
    return CorpusView(events_df, table, X, lengths, seed)


@dataclass
class TrainedSuite:
    stage_b: object
    stage_b_calibrator: object
    stage_b_freq: object
    stage_c: object
    weights: FusionWeights
    thresholds: dict[str, float]
    extra: dict[str, object] = field(default_factory=dict)  # learned baselines (learned_baselines.py)

    def describe(self) -> dict:
        return {
            "weights": {"a": self.weights.weight_a, "b": self.weights.weight_b, "c": self.weights.weight_c},
            "thresholds": self.thresholds,
        }


def _raw_scores(suite_parts: dict, view: CorpusView) -> pd.DataFrame:
    """Per-decision-point scores of every stage, without thresholds."""
    t = view.table
    matrix = to_model_matrix(t)
    points = t[META_COLUMNS].copy()
    points["stage_a_raw"] = matrix.apply(lambda row: stage_a_score(row.to_dict()), axis=1).to_numpy()
    points["stage_a_flag"] = (points["stage_a_raw"] > STAGE_A_THRESHOLD).astype(float)
    points["stage_b"] = calibrate(suite_parts["calibrator"], suite_parts["stage_b"].predict_proba(matrix)[:, 1])
    points["stage_b_freq"] = suite_parts["stage_b_freq"].predict_proba(to_model_matrix(t, FREQUENCY_COLUMNS))[:, 1]
    points["stage_c"] = predict_proba(suite_parts["stage_c"], view.X_seq, view.seq_lengths)
    # tune_fusion_weights reads these historical column names
    points["stage_b_calibrated"] = points["stage_b"]
    points["stage_c_proba"] = points["stage_c"]
    return points


def _fuse(points: pd.DataFrame, weights: FusionWeights) -> np.ndarray:
    w = weights.normalized()
    a = points["stage_a_raw"].map(normalize_stage_a_score).to_numpy()
    return w.weight_a * a + w.weight_b * points["stage_b"].to_numpy() + w.weight_c * points["stage_c"].to_numpy()


def train_suite(view: CorpusView, seed: int, gru_epochs: int = EPOCHS, learned_baselines: bool = True) -> TrainedSuite:
    t = view.table
    train, val = t["split"] == "train", t["split"] == "val"
    y = t["label_attack"]

    X_all = to_model_matrix(t)
    stage_b = train_stage_b(X_all[train], y[train], X_all[val], y[val])
    calibrator = fit_calibrator(stage_b.predict_proba(X_all[val])[:, 1], y[val].to_numpy())

    X_freq = to_model_matrix(t, FREQUENCY_COLUMNS)
    stage_b_freq = train_stage_b(X_freq[train], y[train], X_freq[val], y[val])

    import torch  # after the services package, which fixes the OpenMP load order

    torch.manual_seed(seed)
    y_np = y.to_numpy(dtype=bool)
    tr, va = train.to_numpy(), val.to_numpy()
    stage_c = train_stage_c(
        view.X_seq[tr], view.seq_lengths[tr], y_np[tr],
        view.X_seq[va], view.seq_lengths[va], y_np[va],
        epochs=gru_epochs,
    )

    parts = {"stage_b": stage_b, "calibrator": calibrator, "stage_b_freq": stage_b_freq, "stage_c": stage_c}
    points = _raw_scores(parts, view)
    weights = grid_search_weights(points[val.to_numpy()])
    points["fused"] = _fuse(points, weights)

    extra = {}
    if learned_baselines:
        from eval.research.learned_baselines import LEARNED_BASELINES

        for name, cls in LEARNED_BASELINES.items():
            extra[name] = cls(seed).fit(view)
            points[name] = extra[name].score(view)

    score_columns = {**SCORE_COLUMNS, **{name: name for name in extra}}
    episodes = episode_frame(points, seed, list(score_columns.values()))
    val_ep = episodes[episodes["split"] == "val"]
    thresholds = {
        name: float(best_f1_threshold(val_ep["label_attack"], val_ep[col]))
        for name, col in score_columns.items()
        if name != "stage_a"
    }
    thresholds["stage_a"] = 0.5  # stage_a_flag is already 0/1 at STAGE_A_THRESHOLD
    return TrainedSuite(stage_b, calibrator, stage_b_freq, stage_c, weights, thresholds, extra)


def score_points(suite: TrainedSuite, view: CorpusView) -> pd.DataFrame:
    """Per-decision-point scores and threshold hits for every detector."""
    parts = {
        "stage_b": suite.stage_b,
        "calibrator": suite.stage_b_calibrator,
        "stage_b_freq": suite.stage_b_freq,
        "stage_c": suite.stage_c,
    }
    points = _raw_scores(parts, view)
    points["fused"] = _fuse(points, suite.weights)
    for name, scorer in suite.extra.items():
        points[name] = scorer.score(view)
    for name, col in all_score_columns(suite).items():
        points[f"hit_{name}"] = points[col] >= suite.thresholds[name]
    points["split"] = view.split.to_numpy()
    return points


def all_score_columns(suite: TrainedSuite) -> dict[str, str]:
    return {**SCORE_COLUMNS, **{name: name for name in suite.extra}}


def evaluate_models(suite: TrainedSuite, points: pd.DataFrame, seed: int, split: str = "test") -> dict:
    """Episode-level confusion per detector on `split`, at the suite's
    validation-chosen thresholds."""
    hit_cols = [f"hit_{n}" for n in all_score_columns(suite)]
    episodes = episode_frame(points, seed, hit_cols)
    episodes = episodes[episodes["split"] == split]
    return {name: evaluate(episodes, episodes[f"hit_{name}"].astype(bool)) for name in all_score_columns(suite)}


def evaluate_rules(events_df: pd.DataFrame, seed: int, split: str = "test") -> dict:
    """Splunk and Elastic through the frozen harness, unmodified."""
    return {name: run_detector(events_df, rule, seed, split_filter=split) for name, rule in RULES.items()}


def summarize(result: dict) -> dict:
    """The three headline numbers plus counts, from an evaluate()/run_detector() result."""
    o = result["overall"]
    return {k: o[k] for k in ("precision", "recall", "fpr", "tp", "fp", "tn", "fn")}
