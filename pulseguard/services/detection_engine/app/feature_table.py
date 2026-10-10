"""Builds a labelled per-(gap-based-)burst feature table from a generator
`events.parquet` DataFrame, using the SAME feature-engine pure functions the
live stream would use (`windows.py`, `enrichment.py`) — so what Stage A/B
train and evaluate against is exactly what production would compute, not a
separate offline reimplementation.

Evaluation/training unit is the feature engine's own gap-based burst, NOT
the generator's ground-truth `burst_id` — see DECISIONS.md, "Correction:
Phase 4's planned low-and-slow recall target was wrong", for why a single
`low_and_slow` generator burst decomposes into many single-event gap-based
bursts, each labelled `attack` via its parent `burst_id` but individually
lacking any burst-level signature.
"""

from __future__ import annotations

import pandas as pd

from pulseguard_common.baseline_store import LatencyBaseline
from pulseguard_common.enrichment import CohortBaselineProvider, enrich_burst
from pulseguard_common.windows import pair_prompts_and_decisions, segment_into_bursts


class InMemoryBaselineStore:
    """Batch-training-time stand-in for RedisBaselineStore: same interface,
    plain-dict backed, no Redis dependency. Each user in the benchmark
    corpus contributes at most one generator `burst_id`, so there is no
    cross-user state dependency and no global chronological ordering is
    required across users — only within a single user's own sub-bursts,
    which `build_feature_table` already processes in time order."""

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


def build_feature_table(events_df: pd.DataFrame) -> pd.DataFrame:
    labelled = events_df[events_df["burst_id"].notna()].copy()
    if labelled.empty:
        return pd.DataFrame()

    store = InMemoryBaselineStore()
    cohort = CohortBaselineProvider()
    rows = []

    for generator_burst_id, group in labelled.groupby("burst_id"):
        group = group.sort_values("ts")
        user_id = group.iloc[0]["user_id"]
        label = bool(group.iloc[0]["label_attack"])
        # A parquet round-trip of an object column mixing strings and None
        # re-reads the None as float NaN, not Python None (see DECISIONS.md,
        # "Bug fix: attack_profile NaN vs None"). Normalize at the source so
        # every downstream consumer of this table gets a real None.
        raw_profile = group.iloc[0]["attack_profile"]
        profile = None if pd.isna(raw_profile) else raw_profile
        events = group.to_dict("records")
        pairs = pair_prompts_and_decisions(events)
        gap_bursts = segment_into_bursts(pairs)

        for gap_burst in gap_bursts:
            last_pair = gap_burst[-1]
            match_ts = last_pair.decision_ts or last_pair.prompt_ts
            context_rows = group[group["ts"] == match_ts]
            country = context_rows.iloc[0]["geo_country"] if not context_rows.empty else None
            device_id = context_rows.iloc[0]["device_id"] if not context_rows.empty else "unknown"

            vector = enrich_burst(user_id, gap_burst, country, device_id, store, cohort)
            row = vector.as_dict()
            row["label_attack"] = label
            row["attack_profile"] = profile
            row["generator_burst_id"] = generator_burst_id
            rows.append(row)
    # note: row["user_id"] is already set by vector.as_dict() (BurstFeatureVector
    # carries user_id) -- not duplicated here.

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
