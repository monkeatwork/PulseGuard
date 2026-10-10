"""Response-behaviour feature tests. `test_latency_drift_slope_edge_cases`
covers all four edge cases CLAUDE.md mandates explicitly: single-event
bursts, missing latency values, clock skew, and out-of-order arrival."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pulseguard_common.features_response import (
    MIN_DENIALS_FOR_CAPITULATION,
    approval_latency_z,
    capitulation_flag,
    compute_latency_drift_slope,
    deny_run_length,
    denial_latency_variance,
    post_burst_approval_gap,
)
from pulseguard_common.windows import PromptDecisionPair

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _pair(index: int, decision: str | None, latency_ms: int | None, ingest_offset_s: float = 0.0) -> PromptDecisionPair:
    prompt_ts = T0 + timedelta(seconds=index * 30)
    decision_ts = prompt_ts + timedelta(milliseconds=latency_ms) if latency_ms is not None else None
    ingest_ts = decision_ts + timedelta(seconds=ingest_offset_s) if decision_ts is not None else None
    return PromptDecisionPair(
        prompt_ts=prompt_ts,
        decision_ts=decision_ts,
        decision=decision,
        decision_latency_ms=latency_ms,
        ingest_ts=ingest_ts,
        prompt_index=index,
    )


# --- deny_run_length / capitulation_flag ------------------------------------

def test_deny_run_length_counts_leading_denials():
    pairs = [_pair(0, "deny", 1000), _pair(1, "deny", 900), _pair(2, "approve", 500)]
    assert deny_run_length(pairs) == 2


def test_deny_run_length_zero_when_starts_with_approve():
    pairs = [_pair(0, "approve", 1000)]
    assert deny_run_length(pairs) == 0


def test_capitulation_flag_true_for_2_plus_denials_then_approve():
    pairs = [_pair(0, "deny", 1000), _pair(1, "deny", 900), _pair(2, "approve", 500)]
    assert MIN_DENIALS_FOR_CAPITULATION == 2
    assert capitulation_flag(pairs) is True


def test_capitulation_flag_false_for_single_deny_then_approve():
    pairs = [_pair(0, "deny", 1000), _pair(1, "approve", 500)]
    assert capitulation_flag(pairs) is False


def test_capitulation_flag_false_when_never_approved():
    pairs = [_pair(0, "deny", 1000), _pair(1, "deny", 900)]
    assert capitulation_flag(pairs) is False


# --- latency_drift_slope: the four mandated edge cases ----------------------

def test_latency_drift_slope_edge_case_single_event_burst():
    pairs = [_pair(0, "approve", 3000)]
    result = compute_latency_drift_slope(pairs)
    assert result.slope == 0.0
    assert result.valid is False


def test_latency_drift_slope_edge_case_missing_latency_values():
    # 4 points but 2 have no latency (timeouts) -- must exclude, not crash or NaN
    pairs = [
        _pair(0, "deny", 5000),
        _pair(1, None, None),
        _pair(2, None, None),
        _pair(3, "approve", 800),
    ]
    result = compute_latency_drift_slope(pairs)
    assert result.valid is True
    assert result.n_points_used == 2
    assert result.timeout_count == 2
    assert result.slope < 0  # latency collapsed from 5000ms to 800ms


def test_latency_drift_slope_edge_case_all_latencies_missing():
    pairs = [_pair(0, None, None), _pair(1, None, None), _pair(2, None, None)]
    result = compute_latency_drift_slope(pairs)
    assert result.valid is False
    assert result.slope == 0.0
    assert result.timeout_count == 3


def test_latency_drift_slope_edge_case_clock_skew_excluded():
    # 5 points with a strongly negative fatigue trend, but one point (index 2)
    # has an implausible clock skew and must be excluded from the fit.
    pairs = [
        _pair(0, "deny", 5000),
        _pair(1, "deny", 4000),
        _pair(2, "deny", 100, ingest_offset_s=50.0),  # 50s skew -- corrupt latency
        _pair(3, "deny", 2000),
        _pair(4, "approve", 800),
    ]
    rolling_median_skew = 0.0  # this user's stream is normally not skewed at all
    result = compute_latency_drift_slope(pairs, rolling_median_skew_seconds=rolling_median_skew)
    assert result.skew_excluded_count == 1
    assert result.n_points_used == 4
    assert result.valid is True
    assert result.slope < 0


def test_latency_drift_slope_edge_case_out_of_order_prompt_index_is_respected():
    # Pairs handed in out of chronological order; prompt_index (assigned by
    # segment_into_bursts upstream) is what the regression actually uses.
    ordered_pairs = [_pair(i, "deny" if i < 4 else "approve", 5000 - i * 1000) for i in range(5)]
    shuffled = [ordered_pairs[2], ordered_pairs[0], ordered_pairs[4], ordered_pairs[1], ordered_pairs[3]]
    result_shuffled = compute_latency_drift_slope(shuffled)
    result_ordered = compute_latency_drift_slope(ordered_pairs)
    assert result_shuffled.slope == result_ordered.slope
    assert result_shuffled.valid is True


def test_latency_drift_slope_strongly_negative_for_clear_fatigue_pattern():
    pairs = [_pair(i, "deny" if i < 9 else "approve", 6000 - i * 600) for i in range(10)]
    result = compute_latency_drift_slope(pairs)
    assert result.valid is True
    assert result.slope < -100  # meaningfully negative, not just noise


def test_latency_drift_slope_near_zero_for_stationary_benign_latency():
    pairs = [_pair(i, "approve", 5000) for i in range(10)]
    result = compute_latency_drift_slope(pairs)
    assert result.valid is True
    assert abs(result.slope) < 1e-6


# --- approval_latency_z ------------------------------------------------------

def test_approval_latency_z_computes_standard_score():
    result = approval_latency_z(latency_ms=8000, baseline_mean_ms=5000, baseline_std_ms=1000)
    assert result.valid is True
    assert result.value == 3.0


def test_approval_latency_z_invalid_when_latency_missing():
    result = approval_latency_z(latency_ms=None, baseline_mean_ms=5000, baseline_std_ms=1000)
    assert result.valid is False
    assert result.value is None


def test_approval_latency_z_invalid_when_baseline_std_is_zero():
    result = approval_latency_z(latency_ms=5000, baseline_mean_ms=5000, baseline_std_ms=0)
    assert result.valid is False


# --- post_burst_approval_gap -------------------------------------------------

def test_post_burst_approval_gap_measures_deny_to_approve_interval():
    # index 0 deny: prompt T0, decision T0+1.0s. index 1 approve: prompt
    # T0+30s, decision T0+30.5s. Gap between the two DECISION timestamps:
    # (T0+30.5s) - (T0+1.0s) = 29.5s.
    pairs = [_pair(0, "deny", 1000), _pair(1, "approve", 500)]
    result = post_burst_approval_gap(pairs)
    assert result.valid is True
    assert result.seconds == 29.5


def test_post_burst_approval_gap_invalid_when_no_prior_denial():
    pairs = [_pair(0, "approve", 500)]
    result = post_burst_approval_gap(pairs)
    assert result.valid is False


def test_post_burst_approval_gap_invalid_when_never_approved():
    pairs = [_pair(0, "deny", 1000), _pair(1, "deny", 900)]
    result = post_burst_approval_gap(pairs)
    assert result.valid is False


# --- denial_latency_variance --------------------------------------------------

def test_denial_latency_variance_computed_for_2_plus_denials():
    pairs = [_pair(0, "deny", 1000), _pair(1, "deny", 3000), _pair(2, "approve", 500)]
    result = denial_latency_variance(pairs)
    assert result.valid is True
    assert result.value > 0


def test_denial_latency_variance_invalid_for_fewer_than_2_denials():
    pairs = [_pair(0, "deny", 1000), _pair(1, "approve", 500)]
    result = denial_latency_variance(pairs)
    assert result.valid is False
    assert result.value == 0.0
