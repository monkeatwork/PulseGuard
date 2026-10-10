from __future__ import annotations

from services.detection_engine.app.stage_a_statistical import stage_a_flag, stage_a_score


def _base_vector(**overrides) -> dict:
    base = dict(
        n_prompts=1, approval_latency_z_valid=False, approval_latency_z=None,
        latency_drift_slope_valid=False, latency_drift_slope=0.0, deny_run_length=0,
    )
    base.update(overrides)
    return base


def test_ordinary_single_approval_scores_zero():
    vector = _base_vector()
    assert stage_a_score(vector) == 0.0
    assert stage_a_flag(vector) is False


def test_strong_negative_drift_slope_scores_high():
    vector = _base_vector(latency_drift_slope_valid=True, latency_drift_slope=-1000.0)
    assert stage_a_score(vector) == 2.0
    assert stage_a_flag(vector) is False  # exactly at threshold, not over


def test_extreme_negative_drift_slope_flags():
    vector = _base_vector(latency_drift_slope_valid=True, latency_drift_slope=-1500.0)
    assert stage_a_flag(vector) is True


def test_high_deny_run_length_scores_high():
    vector = _base_vector(deny_run_length=10)
    assert stage_a_score(vector) == 5.0
    assert stage_a_flag(vector) is True


def test_high_volume_prompt_count_scores_high():
    vector = _base_vector(n_prompts=20, prompts_per_window=20)
    assert stage_a_flag(vector) is True


def test_long_but_sparse_session_does_not_count_as_high_volume():
    """A benign power user's 30-prompt day: many prompts per session, few
    per 10-minute window."""
    vector = _base_vector(n_prompts=30, prompts_per_window=2)
    assert stage_a_score(vector) == 0.0


def test_large_approval_latency_z_scores_high():
    vector = _base_vector(approval_latency_z_valid=True, approval_latency_z=5.0)
    assert stage_a_score(vector) == 5.0
    assert stage_a_flag(vector) is True


def test_score_takes_the_max_not_the_sum_of_signals():
    vector = _base_vector(
        approval_latency_z_valid=True, approval_latency_z=3.0,
        deny_run_length=2,
    )
    assert stage_a_score(vector) == 3.0  # max(3.0, 1.0), not 3.0+1.0
