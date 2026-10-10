"""Escalation to an alternate factor after repeated step-up failures
(DECISIONS.md, "Mitigation escalation ceiling"): 3 consecutive failures
within 30 minutes escalates to requiring a different factor — the account
NEVER reaches a locked state, only loses the vulnerable push channel. This
is the anti-DoS invariant CLAUDE.md's evaluation rule #6 requires: the
escalation ceiling must never lock out the legitimate user under sustained
attack.
"""

from __future__ import annotations

from datetime import datetime, timedelta

ESCALATION_FAILURE_THRESHOLD = 3
ESCALATION_WINDOW_SECONDS = 30 * 60


def recent_failure_count(failure_timestamps: list[datetime], now: datetime) -> int:
    window_start = now - timedelta(seconds=ESCALATION_WINDOW_SECONDS)
    return sum(1 for ts in failure_timestamps if ts >= window_start)


def should_escalate(failure_timestamps: list[datetime], now: datetime) -> bool:
    return recent_failure_count(failure_timestamps, now) >= ESCALATION_FAILURE_THRESHOLD
