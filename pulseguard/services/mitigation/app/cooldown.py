"""Step-up cooldown window (DECISIONS.md, "Mitigation escalation ceiling"):
at most 1 forced step-up per user per 5-minute window."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

STEP_UP_COOLDOWN_SECONDS = 5 * 60


def in_cooldown(last_step_up_ts: Optional[datetime], now: datetime) -> bool:
    if last_step_up_ts is None:
        return False
    return (now - last_step_up_ts).total_seconds() < STEP_UP_COOLDOWN_SECONDS
