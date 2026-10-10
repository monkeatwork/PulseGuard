"""KS-test confirms the mimicry attacker's inter-prompt pacing genuinely
matches the target user's own historical distribution -- proving it's
actually mimicking, not just labelled as such (Phase 8 plan gate)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
from scipy import stats

from eval.adversarial.mimicry_attacker import (
    FALLBACK_GAP_SECONDS,
    compute_historical_gaps,
    generate_mimicry_attack,
)
from eval.adversarial.slow_pacing_attacker import SLOW_PACING_GAP_SECONDS, generate_slow_pacing_attack

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _prompt_timestamps(events) -> list[datetime]:
    return sorted(e.ts for e in events if e.event_type == "mfa_prompt")


def test_compute_historical_gaps_basic():
    timestamps = [T0, T0 + timedelta(seconds=100), T0 + timedelta(seconds=250)]
    gaps = compute_historical_gaps(timestamps)
    assert gaps == [100.0, 150.0]


def test_compute_historical_gaps_needs_at_least_two_timestamps():
    assert compute_historical_gaps([T0]) == []
    assert compute_historical_gaps([]) == []


def test_mimicry_attack_pacing_matches_historical_distribution_via_ks_test():
    """Draw the target's historical gaps from a distinctive distribution
    (uniform 1000-2000s -- nothing like any generator's own attack
    pacing), generate a large mimicry attack, and confirm a KS test does
    NOT reject the null hypothesis that the attack's gaps come from the
    same distribution."""
    rng = np.random.default_rng(42)
    historical_gaps = list(rng.uniform(1000, 2000, size=500))

    # Generate many mimicry bursts back-to-back to accumulate enough gap
    # samples for a meaningful KS test.
    all_gaps = []
    ts = T0
    for i in range(30):
        events = generate_mimicry_attack(
            rng, f"user{i}", ts, "device1", "ua1", "10.0.0.1", "US", historical_gaps
        )
        prompt_ts = _prompt_timestamps(events)
        all_gaps.extend((b - a).total_seconds() for a, b in zip(prompt_ts, prompt_ts[1:]))
        ts += timedelta(days=1)

    ks_stat, p_value = stats.ks_2samp(all_gaps, historical_gaps)
    assert p_value > 0.01, f"mimicry gaps diverge from historical distribution (p={p_value})"


def test_mimicry_attack_falls_back_to_default_gap_with_no_history():
    rng = np.random.default_rng(1)
    events = generate_mimicry_attack(rng, "user1", T0, "d1", "ua1", "10.0.0.1", "US", historical_gap_seconds=[])
    prompt_ts = _prompt_timestamps(events)
    gaps = [(b - a).total_seconds() for a, b in zip(prompt_ts, prompt_ts[1:])]
    for gap in gaps:
        # observed gap = fixed fallback gap + the preceding decision's own
        # latency (a few seconds), so it's always slightly above, never below
        assert gap >= FALLBACK_GAP_SECONDS
        assert gap < FALLBACK_GAP_SECONDS + 20.0


def test_mimicry_attack_is_labelled_as_attack():
    rng = np.random.default_rng(2)
    events = generate_mimicry_attack(rng, "user1", T0, "d1", "ua1", "10.0.0.1", "US", [600.0, 900.0])
    assert all(e.label_attack for e in events)
    assert all(e.attack_profile == "mimicry_adversarial" for e in events)


def test_slow_pacing_attack_uses_exact_5_minute_gaps():
    rng = np.random.default_rng(3)
    events = generate_slow_pacing_attack(rng, "user1", T0, "d1", "ua1", "10.0.0.1", "US")
    prompt_ts = _prompt_timestamps(events)
    gaps = [(b - a).total_seconds() for a, b in zip(prompt_ts, prompt_ts[1:])]
    assert SLOW_PACING_GAP_SECONDS == 300
    for gap in gaps:
        # gap = fixed 300s + the previous event's own decision latency
        assert gap >= 300.0
        assert gap < 320.0  # latency is a few seconds at most


def test_slow_pacing_attack_is_labelled_as_attack():
    rng = np.random.default_rng(4)
    events = generate_slow_pacing_attack(rng, "user1", T0, "d1", "ua1", "10.0.0.1", "US")
    assert all(e.label_attack for e in events)
    assert all(e.attack_profile == "slow_pacing_adversarial" for e in events)
