"""Builds event sequences for Stage C (CLAUDE.md: "GRU over the event
sequence... catches low-and-slow").

Stage C sees the raw step-by-step sequence of a SESSION (sessions.py), so
it can connect an early denial to a later approval across a low-and-slow
episode's 20-40 minute gaps. Like Stage A/B (feature_table.py), it is
scored at every decision point on the session-so-far -- the live path
receives exactly that prefix in each enriched message -- and an episode is
predicted positive if any decision point crosses the threshold. Rows come
from the same `iter_decision_points` iterator as the feature table, so the
two line up one-to-one.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from pulseguard_common.sessions import session_pairs
from pulseguard_common.windows import PromptDecisionPair

SEQUENCE_LENGTH = 20  # DECISIONS.md, "Stage C (GRU) architecture"
STEP_FEATURE_DIM = 6

# Normalizing constant for log1p(milliseconds)/LOG_SCALE and log1p(seconds)/
# LOG_SCALE -- keeps typical values (latencies in the thousands of ms, gaps
# up to tens of thousands of seconds for low-and-slow) roughly in [0, 2].
LOG_SCALE = 10.0


def _pair_to_step_features(pair: PromptDecisionPair, gap_seconds: float) -> list[float]:
    is_deny = 1.0 if pair.decision == "deny" else 0.0
    is_approve = 1.0 if pair.decision == "approve" else 0.0
    is_timeout_or_missing = 1.0 if pair.decision is None else 0.0
    has_latency = 1.0 if pair.decision_latency_ms is not None else 0.0
    log_latency = (
        math.log1p(pair.decision_latency_ms) / LOG_SCALE if pair.decision_latency_ms is not None else 0.0
    )
    log_gap = math.log1p(max(gap_seconds, 0.0)) / LOG_SCALE
    return [is_deny, is_approve, is_timeout_or_missing, has_latency, log_latency, log_gap]


def pairs_to_sequence(
    pairs: list[PromptDecisionPair], max_len: int = SEQUENCE_LENGTH
) -> tuple[np.ndarray, int]:
    """Returns (padded_sequence[max_len, STEP_FEATURE_DIM], true_length).
    Keeps the LAST max_len steps when longer (most recent history is what
    an online detector would actually have access to); zero-pads at the
    END when shorter, paired with `true_length` for masking/packing."""
    ordered = sorted(pairs, key=lambda p: p.prompt_ts)
    steps = []
    prev_ts = None
    for pair in ordered:
        gap = (pair.prompt_ts - prev_ts).total_seconds() if prev_ts is not None else 0.0
        steps.append(_pair_to_step_features(pair, gap))
        prev_ts = pair.prompt_ts

    steps = steps[-max_len:]
    true_length = max(len(steps), 1)  # a length of 0 breaks packed-sequence APIs
    padded = np.zeros((max_len, STEP_FEATURE_DIM), dtype=np.float32)
    if steps:
        padded[: len(steps)] = np.array(steps, dtype=np.float32)
    return padded, true_length


def build_sequence_dataset(
    events_df: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str], list, list[str]]:
    """Returns (X[n, max_len, dim] float32, lengths[n] int, y[n] bool,
    user_ids[n], attack_profiles[n], episode_ids[n]) -- one row per decision
    point, in the same order as feature_table.build_feature_table."""
    from services.detection_engine.app.feature_table import iter_decision_points

    X, lengths, y, user_ids, profiles, burst_ids = [], [], [], [], [], []
    for point, _ in iter_decision_points(events_df):
        seq, length = pairs_to_sequence(session_pairs(point.prefix_events))
        X.append(seq)
        lengths.append(length)
        y.append(point.label_attack)
        user_ids.append(point.user_id)
        profiles.append(point.attack_profile)
        burst_ids.append(point.episode_id)

    if not X:
        return (
            np.zeros((0, SEQUENCE_LENGTH, STEP_FEATURE_DIM), dtype=np.float32),
            np.zeros((0,), dtype=np.int64),
            np.zeros((0,), dtype=bool),
            [],
            [],
            [],
        )

    return (
        np.stack(X),
        np.array(lengths, dtype=np.int64),
        np.array(y, dtype=bool),
        user_ids,
        profiles,
        burst_ids,
    )
