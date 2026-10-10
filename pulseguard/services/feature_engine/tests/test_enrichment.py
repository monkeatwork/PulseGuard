"""Tests for the per-burst orchestration layer, using a fake in-memory
baseline store so these stay fast unit tests (the real Redis-backed store
is covered by test_baseline_store_integration.py)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pytest

from pulseguard_common.enrichment import CohortBaselineProvider, enrich_burst
from pulseguard_common.windows import PromptDecisionPair

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


@dataclass
class _FakeLatencyBaseline:
    event_count: int = 0
    mean_ms: float = 0.0
    std_ms: float = 0.0
    is_cold_start: bool = True


@dataclass
class _FakeBaselineStore:
    latency: _FakeLatencyBaseline = field(default_factory=_FakeLatencyBaseline)
    countries: set = field(default_factory=set)
    devices: set = field(default_factory=set)
    rate_updates: list = field(default_factory=list)

    def load_latency(self, user_id: str):
        return self.latency

    def update_latency(self, user_id: str, latency_ms: float):
        n = self.latency.event_count
        new_mean = (self.latency.mean_ms * n + latency_ms) / (n + 1)
        self.latency = _FakeLatencyBaseline(
            event_count=n + 1, mean_ms=new_mean, std_ms=max(self.latency.std_ms, 1.0),
            is_cold_start=(n + 1) < 30,
        )

    def update_rate(self, user_id: str, inter_arrival_seconds: float):
        self.rate_updates.append(inter_arrival_seconds)

    def is_country_known(self, user_id: str, country: str) -> bool:
        return country in self.countries

    def record_country(self, user_id: str, country: str) -> None:
        self.countries.add(country)

    def is_device_known(self, user_id: str, device_id: str) -> bool:
        return device_id in self.devices

    def record_device(self, user_id: str, device_id: str) -> None:
        self.devices.add(device_id)


def _pair(index: int, decision: str | None, latency_ms: int | None) -> PromptDecisionPair:
    prompt_ts = T0 + timedelta(seconds=index * 30)
    decision_ts = prompt_ts + timedelta(milliseconds=latency_ms) if latency_ms is not None else None
    return PromptDecisionPair(
        prompt_ts=prompt_ts, decision_ts=decision_ts, decision=decision,
        decision_latency_ms=latency_ms, ingest_ts=decision_ts, prompt_index=index,
    )


def test_enrich_burst_returns_full_feature_vector_with_no_nans():
    pairs = [_pair(i, "deny" if i < 9 else "approve", 6000 - i * 600) for i in range(10)]
    store = _FakeBaselineStore()
    vector = enrich_burst("user1", pairs, "US", "device-1", store, CohortBaselineProvider())

    assert vector.n_prompts == 10
    assert vector.deny_run_length == 9
    assert vector.capitulation_flag is True
    assert vector.latency_drift_slope_valid is True
    assert vector.latency_drift_slope < 0
    # every numeric field must be a real float/int/bool, never NaN
    for key, value in vector.as_dict().items():
        if isinstance(value, float):
            assert value == value, f"{key} is NaN"  # NaN != NaN


def test_enrich_burst_marks_novel_device_and_country_on_first_sight():
    pairs = [_pair(0, "approve", 3000)]
    store = _FakeBaselineStore()
    vector = enrich_burst("user1", pairs, "FR", "new-device", store, CohortBaselineProvider())
    assert vector.geo_novelty is True
    assert vector.device_novelty is True

    # second burst from the same context is no longer novel
    vector2 = enrich_burst("user1", pairs, "FR", "new-device", store, CohortBaselineProvider())
    assert vector2.geo_novelty is False
    assert vector2.device_novelty is False


def test_enrich_burst_updates_latency_baseline_only_on_approval():
    pairs_deny_only = [_pair(0, "deny", 1000), _pair(1, "deny", 900)]
    store = _FakeBaselineStore()
    enrich_burst("user1", pairs_deny_only, "US", "device-1", store, CohortBaselineProvider())
    assert store.latency.event_count == 0  # no approval -> no latency sample recorded

    pairs_with_approve = [_pair(0, "deny", 1000), _pair(1, "approve", 500)]
    enrich_burst("user1", pairs_with_approve, "US", "device-1", store, CohortBaselineProvider())
    assert store.latency.event_count == 1


def test_enrich_burst_single_event_burst_has_invalid_slope_not_nan():
    pairs = [_pair(0, "approve", 3000)]
    store = _FakeBaselineStore()
    vector = enrich_burst("user1", pairs, "US", "device-1", store, CohortBaselineProvider())
    assert vector.latency_drift_slope == 0.0
    assert vector.latency_drift_slope_valid is False


def test_enrich_burst_cold_start_uses_blended_cohort_baseline():
    pairs = [_pair(0, "approve", 3000)]
    store = _FakeBaselineStore()  # event_count=0 -> fully cold start
    cohort = CohortBaselineProvider(cohort_mean_ms=9000.0)
    vector = enrich_burst("user1", pairs, "US", "device-1", store, cohort)
    # approval_latency_z should be computable (baseline_std defaults to >=1.0)
    assert vector.approval_latency_z_valid is True
    assert vector.baseline_is_cold_start is True
