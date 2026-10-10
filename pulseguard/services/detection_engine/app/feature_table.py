"""Builds the labelled feature table Stage A/B train and evaluate on, using
the SAME pure functions the live feature engine calls (`sessions.py`,
`enrichment.py`) -- so what the models see offline is exactly what
production computes, not a separate reimplementation.

Unit: one row per DECISION POINT of a session (DECISIONS.md 2026-10-11,
"Session-level scoring"). For every generator episode (`burst_id`), the
user's events are split into sessions (`sessions.SESSION_GAP_THRESHOLD_SECONDS`)
and, at every `mfa_decision`, the session-so-far is featurised -- precisely
what `streaming_app.py` emits live on each decision event. An episode is
predicted positive if ANY of its decision points crosses the threshold,
which is the live alerting rule (the first crossing raises the alert).

This replaces the old per-5-minute-fragment unit, under which a
low-and-slow episode decomposed into isolated single-prompt fragments with
every response-behaviour feature undefined (REMEDIATION_TASK.md A1/A2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Optional

import pandas as pd

from pulseguard_common.baseline_store import LatencyBaseline
from pulseguard_common.enrichment import CohortBaselineProvider, commit_baselines, compute_features
from pulseguard_common.sessions import (
    decision_point_prefixes,
    segment_events_into_sessions,
    session_context,
    session_pairs,
)


class InMemoryBaselineStore:
    """Batch-training-time stand-in for RedisBaselineStore: same interface,
    plain-dict backed, no Redis dependency. Baselines are advanced once per
    closed session (commit_baselines), exactly as the live feature engine
    does when a session closes."""

    def __init__(self):
        self._latency: dict[str, LatencyBaseline] = {}
        self._countries: dict[str, set] = {}
        self._devices: dict[str, set] = {}

    def load_latency(self, user_id):
        return self._latency.setdefault(user_id, LatencyBaseline())

    def update_latency(self, user_id, latency_ms):
        self.load_latency(user_id).update(latency_ms)

    def update_rate(self, user_id, inter_arrival_seconds):
        pass

    def is_country_known(self, user_id, country):
        return country in self._countries.get(user_id, set())

    def record_country(self, user_id, country):
        self._countries.setdefault(user_id, set()).add(country)

    def is_device_known(self, user_id, device_id):
        return device_id in self._devices.get(user_id, set())

    def record_device(self, user_id, device_id):
        self._devices.setdefault(user_id, set()).add(device_id)


@dataclass
class DecisionPoint:
    episode_id: str  # the generator's ground-truth burst_id (evaluation unit)
    user_id: str
    label_attack: bool
    attack_profile: Optional[str]
    session_index: int
    decision_index: int
    prefix_events: list[dict]


def _normalise_profile(raw) -> Optional[str]:
    # A parquet round-trip of an object column mixing strings and None
    # re-reads None as float NaN (DECISIONS.md, "Bug fix: attack_profile NaN
    # vs None"). Normalise at the source.
    return None if raw is None or (isinstance(raw, float) and pd.isna(raw)) else raw


def iter_decision_points(
    events_df: pd.DataFrame, store: Optional[InMemoryBaselineStore] = None
) -> Iterator[tuple[DecisionPoint, Optional[object]]]:
    """Yields every decision point of every labelled episode, in a fixed
    order (episode id, then time). When `store` is given, also yields the
    feature vector computed against it, committing baselines as each session
    closes. Shared by feature_table and sequence_dataset so their rows line
    up one-to-one."""
    labelled = events_df[events_df["burst_id"].notna()]
    if labelled.empty:
        return
    cohort = CohortBaselineProvider()
    for episode, group in labelled.groupby("burst_id", sort=True):
        group = group.sort_values("ts")
        first = group.iloc[0]
        user_id = str(first["user_id"])
        label = bool(first["label_attack"])
        profile = _normalise_profile(first["attack_profile"])
        events = group.to_dict("records")
        for s_idx, session in enumerate(segment_events_into_sessions(events)):
            for d_idx, prefix in decision_point_prefixes(session):
                point = DecisionPoint(str(episode), user_id, label, profile, s_idx, d_idx, prefix)
                vector = None
                if store is not None:
                    country, device_id = session_context(prefix)
                    vector = compute_features(user_id, session_pairs(prefix), country, device_id, store, cohort)
                yield point, vector
            if store is not None:
                country, device_id = session_context(session)
                commit_baselines(user_id, session_pairs(session), country, device_id, store)


def build_feature_table(events_df: pd.DataFrame) -> pd.DataFrame:
    store = InMemoryBaselineStore()
    rows = []
    for point, vector in iter_decision_points(events_df, store):
        row = vector.as_dict()  # carries user_id
        row["label_attack"] = point.label_attack
        row["attack_profile"] = point.attack_profile
        row["generator_burst_id"] = point.episode_id
        row["session_index"] = point.session_index
        row["decision_index"] = point.decision_index
        rows.append(row)
    return pd.DataFrame(rows)


# Numeric feature columns fed to Stage B (and used to compute Stage A's
# score). Excludes identifiers/labels, which are metadata, not model input.
FEATURE_COLUMNS = [
    "n_prompts",
    "prompts_per_window",
    "inter_prompt_mean",
    "inter_prompt_std",
    "burst_duration_seconds",
    "off_hours_flag",
    "geo_novelty",
    "device_novelty",
    "deny_run_length",
    "capitulation_flag",
    "approval_latency_z",
    "approval_latency_z_valid",
    "latency_drift_slope",
    "latency_drift_slope_valid",
    "post_burst_approval_gap_seconds",
    "post_burst_approval_gap_valid",
    "denial_latency_variance",
    "denial_latency_variance_valid",
    "baseline_is_cold_start",
]

# Subset of FEATURE_COLUMNS that are the project's actual contribution
# (CLAUDE.md, "Response-behaviour features"), used by the Phase 8 ablation.
RESPONSE_BEHAVIOUR_COLUMNS = [
    "deny_run_length",
    "capitulation_flag",
    "approval_latency_z",
    "approval_latency_z_valid",
    "latency_drift_slope",
    "latency_drift_slope_valid",
    "post_burst_approval_gap_seconds",
    "post_burst_approval_gap_valid",
    "denial_latency_variance",
    "denial_latency_variance_valid",
]

FREQUENCY_COLUMNS = [c for c in FEATURE_COLUMNS if c not in RESPONSE_BEHAVIOUR_COLUMNS]


def to_model_matrix(feature_table: pd.DataFrame, columns: list[str] = FEATURE_COLUMNS) -> pd.DataFrame:
    """Fills missing/invalid numeric feature values with 0 AFTER their
    paired `_valid` flag already tells the model whether to trust them —
    consistent with features_response.py's "explicit validity flag, never a
    silently fabricated number" convention (DECISIONS.md, Phase 3)."""
    matrix = feature_table[columns].copy()
    for col in matrix.columns:
        if matrix[col].dtype == bool:
            matrix[col] = matrix[col].astype(int)
        else:
            matrix[col] = pd.to_numeric(matrix[col], errors="coerce").fillna(0.0)
    return matrix
