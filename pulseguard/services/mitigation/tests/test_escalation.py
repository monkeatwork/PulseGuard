from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.mitigation.app.escalation import (
    ESCALATION_FAILURE_THRESHOLD,
    ESCALATION_WINDOW_SECONDS,
    recent_failure_count,
    should_escalate,
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_no_failures_never_escalates():
    assert should_escalate([], T0) is False


def test_exactly_2_failures_does_not_escalate():
    failures = [T0, T0 + timedelta(minutes=1)]
    assert should_escalate(failures, T0 + timedelta(minutes=2)) is False


def test_exactly_3_failures_within_window_escalates():
    failures = [T0, T0 + timedelta(minutes=1), T0 + timedelta(minutes=2)]
    assert should_escalate(failures, T0 + timedelta(minutes=3)) is True


def test_old_failures_outside_window_are_not_counted():
    failures = [T0]  # a single old failure, long expired
    now = T0 + timedelta(seconds=ESCALATION_WINDOW_SECONDS + 1)
    assert recent_failure_count(failures, now) == 0
    assert should_escalate(failures, now) is False


def test_mixed_old_and_recent_failures_counts_only_recent():
    now = T0 + timedelta(minutes=40)
    failures = [
        T0,  # 40 min ago -- outside the 30-min window
        now - timedelta(minutes=10),
        now - timedelta(minutes=5),
        now - timedelta(minutes=1),
    ]
    assert recent_failure_count(failures, now) == 3
    assert should_escalate(failures, now) is True


def test_threshold_and_window_match_decisions_md():
    assert ESCALATION_FAILURE_THRESHOLD == 3
    assert ESCALATION_WINDOW_SECONDS == 30 * 60
