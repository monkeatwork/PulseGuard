"""Per-user adaptive baseline store (L3), backed by Redis.

River's `stats.EWMean`/`stats.EWVar` provide the incremental EWMA baselines
(DECISIONS.md, "EWMA decay rates": alpha=0.15 latency, alpha=0.05 rate).
Persisted via pickle — see DECISIONS.md, Phase 3 feature-engine design
choices, for why (River's internal state has no stable public
introspection API in the installed version, but round-trips through
pickle correctly).

This module is the only place that talks to Redis for baseline state; the
pure feature functions in features_frequency.py/features_response.py never
import Redis directly, so they stay unit-testable in isolation from the
stream (CLAUDE.md, "Working conventions").
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass, field

from river import stats

from pulseguard_common.redis_keys import (
    baseline_latency_key,
    baseline_rate_key,
    known_countries_key,
    known_devices_key,
)
from pulseguard_common.cohort_fallback import COLD_START_THRESHOLD_EVENTS

LATENCY_EWMA_ALPHA = 0.15
RATE_EWMA_ALPHA = 0.05


@dataclass
class LatencyBaseline:
    mean: stats.EWMean = field(default_factory=lambda: stats.EWMean(fading_factor=LATENCY_EWMA_ALPHA))
    var: stats.EWVar = field(default_factory=lambda: stats.EWVar(fading_factor=LATENCY_EWMA_ALPHA))
    event_count: int = 0

    def update(self, latency_ms: float) -> None:
        self.mean.update(latency_ms)
        self.var.update(latency_ms)
        self.event_count += 1

    @property
    def mean_ms(self) -> float:
        return self.mean.get() or 0.0

    @property
    def std_ms(self) -> float:
        variance = self.var.get()
        return variance ** 0.5 if variance and variance > 0 else 0.0

    @property
    def is_cold_start(self) -> bool:
        return self.event_count < COLD_START_THRESHOLD_EVENTS


@dataclass
class RateBaseline:
    mean: stats.EWMean = field(default_factory=lambda: stats.EWMean(fading_factor=RATE_EWMA_ALPHA))

    def update(self, inter_arrival_seconds: float) -> None:
        self.mean.update(inter_arrival_seconds)

    @property
    def mean_seconds(self) -> float:
        return self.mean.get() or 0.0


class RedisBaselineStore:
    """Thin persistence layer. Every method round-trips through Redis so
    state survives a service restart (Phase 3 gate: "baseline state
    persists across a service restart")."""

    def __init__(self, redis_client):
        self._redis = redis_client

    def load_latency(self, user_id: str) -> LatencyBaseline:
        raw = self._redis.get(baseline_latency_key(user_id))
        if raw is None:
            return LatencyBaseline()
        return pickle.loads(raw)

    def save_latency(self, user_id: str, baseline: LatencyBaseline) -> None:
        self._redis.set(baseline_latency_key(user_id), pickle.dumps(baseline))

    def update_latency(self, user_id: str, latency_ms: float) -> LatencyBaseline:
        baseline = self.load_latency(user_id)
        baseline.update(latency_ms)
        self.save_latency(user_id, baseline)
        return baseline

    def load_rate(self, user_id: str) -> RateBaseline:
        raw = self._redis.get(baseline_rate_key(user_id))
        if raw is None:
            return RateBaseline()
        return pickle.loads(raw)

    def save_rate(self, user_id: str, baseline: RateBaseline) -> None:
        self._redis.set(baseline_rate_key(user_id), pickle.dumps(baseline))

    def update_rate(self, user_id: str, inter_arrival_seconds: float) -> RateBaseline:
        baseline = self.load_rate(user_id)
        baseline.update(inter_arrival_seconds)
        self.save_rate(user_id, baseline)
        return baseline

    def is_country_known(self, user_id: str, country: str) -> bool:
        return bool(self._redis.sismember(known_countries_key(user_id), country))

    def record_country(self, user_id: str, country: str) -> None:
        self._redis.sadd(known_countries_key(user_id), country)

    def known_countries(self, user_id: str) -> set[str]:
        members = self._redis.smembers(known_countries_key(user_id))
        return {m.decode() if isinstance(m, bytes) else m for m in members}

    def is_device_known(self, user_id: str, device_id: str) -> bool:
        return bool(self._redis.sismember(known_devices_key(user_id), device_id))

    def record_device(self, user_id: str, device_id: str) -> None:
        self._redis.sadd(known_devices_key(user_id), device_id)

    def known_devices(self, user_id: str) -> set[str]:
        members = self._redis.smembers(known_devices_key(user_id))
        return {m.decode() if isinstance(m, bytes) else m for m in members}
