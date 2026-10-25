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


# --- Fatigue strength / shape / null model (FatigueConfig) -------------------

from benchmark.generator.latency_models import (  # noqa: E402
    DUOLUNGO_APPROVE_LATENCY_MU,
    DUOLUNGO_APPROVE_LATENCY_SIGMA,
    FATIGUE_MU_END,
    FATIGUE_MU_START,
    FATIGUE_SIGMA,
    FatigueConfig,
    benign_params,
    episode_strength,
    fatigue_params,
    fatigue_progress,
)


def test_default_config_reproduces_the_original_draws_exactly():
    """FatigueConfig() must not move a single draw: the seed-42 corpus the
    committed models were trained on depends on it."""
    rng_new, rng_old = np.random.default_rng(9), np.random.default_rng(9)
    for i in range(12):
        new = sample_fatigue_latency_ms(rng_new, i, 12, "deny", FatigueConfig(), 1.0)
        mu = FATIGUE_MU_START + (i / 11) * (FATIGUE_MU_END - FATIGUE_MU_START)
        old = max(MIN_LATENCY_MS, int(round(rng_old.lognormal(mean=mu, sigma=FATIGUE_SIGMA) * 1000)))
        assert new == old


@pytest.mark.parametrize("decision", ["approve", "deny"])
def test_matched_null_at_strength_zero_is_exactly_benign(decision):
    config = FatigueConfig(strength=0.0, null_model="matched")
    for i in range(10):
        assert fatigue_params(i, 10, decision, config) == benign_params(decision)


def test_matched_null_lure_at_strength_zero_is_a_benign_approval():
    config = FatigueConfig(strength=0.0, null_model="matched")
    a, b = np.random.default_rng(3), np.random.default_rng(3)
    assert [sample_lure_latency_ms(a, config) for _ in range(50)] == [
        sample_benign_approve_latency_ms(b) for _ in range(50)
    ]


def test_legacy_null_at_strength_zero_still_differs_from_benign():
    """Documents WHY the matched null exists: the original model keeps a
    tighter spread at strength 0, so it is not signal-free."""
    mu, sigma = fatigue_params(5, 10, "deny", FatigueConfig(strength=0.0))
    assert (mu, sigma) != benign_params("deny")


def test_late_burst_latency_falls_monotonically_with_strength():
    medians = []
    for s in (0.0, 0.25, 0.5, 0.75, 1.0):
        rng = np.random.default_rng(4)
        config = FatigueConfig(strength=s, null_model="matched")
        medians.append(np.median([sample_fatigue_latency_ms(rng, 9, 10, "deny", config) for _ in range(3000)]))
    assert medians == sorted(medians, reverse=True)
    assert medians[-1] < medians[0] * 0.4


@pytest.mark.parametrize("shape", ["linear", "exponential", "step"])
def test_every_shape_runs_from_no_collapse_to_full_collapse(shape):
    progress = [fatigue_progress(i, 11, shape) for i in range(11)]
    assert progress[0] == 0.0 and progress[-1] == pytest.approx(1.0)
    assert progress == sorted(progress)


def test_exponential_collapses_earlier_than_linear():
    assert fatigue_progress(3, 11, "exponential") > fatigue_progress(3, 11, "linear")


def test_homogeneous_episode_strength_draws_nothing():
    rng = np.random.default_rng(5)
    state = rng.bit_generator.state
    assert episode_strength(rng, FatigueConfig(strength=0.6)) == 0.6
    assert rng.bit_generator.state == state


def test_heterogeneous_episode_strength_varies_and_stays_bounded():
    rng = np.random.default_rng(6)
    config = FatigueConfig(strength=1.0, heterogeneity=0.5)
    draws = [episode_strength(rng, config) for _ in range(2000)]
    assert min(draws) >= -0.5 and max(draws) <= 2.0
    assert np.std(draws) > 0.3
    assert any(d < 0 for d in draws)  # some victims slow down


def test_duolungo_fit_matches_the_published_quartiles():
    """Prapty & Tsudik (USEC 2026): median 6.89 s, Q1 4.82 s, Q3 10.47 s."""
    from scipy.stats import lognorm

    dist = lognorm(s=DUOLUNGO_APPROVE_LATENCY_SIGMA, scale=np.exp(DUOLUNGO_APPROVE_LATENCY_MU))
    assert dist.median() == pytest.approx(6.89, rel=0.01)
    assert dist.ppf(0.25) == pytest.approx(4.82, rel=0.05)
    assert dist.ppf(0.75) == pytest.approx(10.47, rel=0.05)
