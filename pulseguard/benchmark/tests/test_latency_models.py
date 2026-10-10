"""Unit tests for benchmark/generator/latency_models.py.

Pure numeric checks — no I/O, no Docker, no RBA dataset dependency, so
these run in any environment (see CLAUDE.md's "feature computation is pure"
convention, applied here to the generator's latency sampling).
"""

from __future__ import annotations

import numpy as np
import pytest

from benchmark.generator.latency_models import (
    MIN_LATENCY_MS,
    fatigue_mu_at,
    sample_benign_approve_latency_ms,
    sample_benign_deny_latency_ms,
    sample_fatigue_latency_ms,
    sample_lure_latency_ms,
    LURE_LATENCY_FLOOR_MS,
    LURE_LATENCY_CEILING_MS,
)


def test_benign_approve_latency_median_is_a_few_seconds():
    rng = np.random.default_rng(1)
    samples = [sample_benign_approve_latency_ms(rng) for _ in range(5000)]
    median = np.median(samples)
    assert 3000 < median < 8000


def test_benign_deny_latency_is_faster_than_approve_on_average():
    rng = np.random.default_rng(2)
    approve = [sample_benign_approve_latency_ms(rng) for _ in range(5000)]
    deny = [sample_benign_deny_latency_ms(rng) for _ in range(5000)]
    assert np.mean(deny) < np.mean(approve)


def test_fatigue_mu_decays_monotonically_across_burst():
    burst_length = 10
    mus = [fatigue_mu_at(i, burst_length) for i in range(burst_length)]
    assert mus == sorted(mus, reverse=True)
    assert mus[0] > mus[-1]


def test_fatigue_latency_collapses_across_burst():
    """The core claim of the project: latency at the end of a burst should
    be substantially lower than at the start (negative drift slope)."""
    rng = np.random.default_rng(3)
    burst_length = 15
    early = [sample_fatigue_latency_ms(rng, 0, burst_length) for _ in range(2000)]
    late = [
        sample_fatigue_latency_ms(rng, burst_length - 1, burst_length) for _ in range(2000)
    ]
    assert np.median(late) < np.median(early) * 0.6


def test_fatigue_single_event_burst_does_not_crash():
    rng = np.random.default_rng(4)
    latency = sample_fatigue_latency_ms(rng, 0, 1)
    assert latency >= MIN_LATENCY_MS


def test_lure_latency_within_configured_floor_and_ceiling():
    rng = np.random.default_rng(5)
    samples = [sample_lure_latency_ms(rng) for _ in range(1000)]
    assert min(samples) >= LURE_LATENCY_FLOOR_MS
    assert max(samples) <= LURE_LATENCY_CEILING_MS


@pytest.mark.parametrize("sampler", [sample_benign_approve_latency_ms, sample_benign_deny_latency_ms])
def test_latencies_never_below_floor(sampler):
    rng = np.random.default_rng(6)
    samples = [sampler(rng) for _ in range(2000)]
    assert min(samples) >= MIN_LATENCY_MS
