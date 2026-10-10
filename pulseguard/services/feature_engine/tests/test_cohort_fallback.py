"""Cohort blend ramp values at the exact points DECISIONS.md calls out:
n=0, 15, 29, 30, 100."""

from __future__ import annotations

from pulseguard_common.cohort_fallback import (
    COLD_START_THRESHOLD_EVENTS,
    blend_baseline,
    cohort_blend_ramp,
    is_cold_start,
)


def test_ramp_at_zero_events_is_zero():
    assert cohort_blend_ramp(0) == 0.0


def test_ramp_at_15_events_is_half():
    assert cohort_blend_ramp(15) == 0.5


def test_ramp_at_29_events_is_just_under_one():
    assert cohort_blend_ramp(29) == 29 / 30


def test_ramp_at_30_events_is_exactly_one():
    assert cohort_blend_ramp(30) == 1.0


def test_ramp_at_100_events_is_clamped_to_one():
    assert cohort_blend_ramp(100) == 1.0


def test_blend_at_zero_events_is_exactly_50_50():
    blended = blend_baseline(user_baseline=10.0, cohort_baseline=20.0, user_event_count=0)
    assert blended == 15.0  # 0.5*10 + 0.5*20


def test_blend_at_30_events_is_pure_user_baseline():
    blended = blend_baseline(user_baseline=10.0, cohort_baseline=20.0, user_event_count=30)
    assert blended == 10.0


def test_blend_at_15_events_is_intermediate():
    # ramp=0.5: 0.5*user + 0.5*(0.5*cohort+0.5*user) = 0.75*user + 0.25*cohort
    blended = blend_baseline(user_baseline=10.0, cohort_baseline=20.0, user_event_count=15)
    assert blended == 0.75 * 10.0 + 0.25 * 20.0


def test_blend_at_100_events_is_pure_user_baseline():
    blended = blend_baseline(user_baseline=10.0, cohort_baseline=20.0, user_event_count=100)
    assert blended == 10.0


def test_is_cold_start_boundary():
    assert is_cold_start(29) is True
    assert is_cold_start(30) is False
    assert is_cold_start(0) is True


def test_cold_start_threshold_matches_decisions_md():
    assert COLD_START_THRESHOLD_EVENTS == 30
