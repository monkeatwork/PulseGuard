"""The ablation's "NO MEASURABLE LIFT" flag must trigger on a near-zero
delta and must NOT trigger on a large, real delta -- and it must not be
something a caller can quietly suppress (CLAUDE.md: report a negative
result honestly, don't tune the evaluation until the feature looks good).
"""

from __future__ import annotations

import pytest

from eval.ablation.run_ablation import NO_LIFT_NOISE_FLOOR_PERCENTAGE_POINTS, compute_lift_flags


def test_near_zero_delta_triggers_no_measurable_lift():
    flags = compute_lift_flags(freq_recall=0.80, full_recall=0.805, minus_slope_recall=0.803)
    assert flags["no_measurable_lift_response_behaviour"] is True
    assert flags["no_measurable_lift_latency_drift_slope"] is True


def test_large_delta_does_not_trigger_no_measurable_lift():
    flags = compute_lift_flags(freq_recall=0.30, full_recall=0.90, minus_slope_recall=0.60)
    assert flags["no_measurable_lift_response_behaviour"] is False
    assert flags["no_measurable_lift_latency_drift_slope"] is False


def test_delta_exactly_at_the_noise_floor_boundary():
    # exactly at the floor is NOT "less than" -- boundary belongs to "has lift"
    delta_recall = NO_LIFT_NOISE_FLOOR_PERCENTAGE_POINTS / 100
    flags = compute_lift_flags(freq_recall=0.50, full_recall=0.50 + delta_recall, minus_slope_recall=0.50)
    assert flags["no_measurable_lift_response_behaviour"] is False


def test_negative_lift_is_also_flagged_as_no_measurable_lift_when_small():
    # response-behaviour features making things slightly WORSE is still
    # "no measurable lift" (in either direction), not silently ignored
    flags = compute_lift_flags(freq_recall=0.801, full_recall=0.80, minus_slope_recall=0.80)
    assert flags["response_behaviour_lift_percentage_points"] < 0
    assert flags["no_measurable_lift_response_behaviour"] is True


def test_lift_percentage_points_computed_correctly():
    flags = compute_lift_flags(freq_recall=0.5, full_recall=0.75, minus_slope_recall=0.6)
    assert flags["response_behaviour_lift_percentage_points"] == pytest.approx(25.0)
    assert flags["latency_drift_slope_lift_percentage_points"] == pytest.approx(15.0)
