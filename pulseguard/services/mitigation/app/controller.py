"""Mitigation controller (L5): decides which mitigation action to take for
an alerted user and tracks the per-user cooldown/escalation state.

Anti-DoS invariant (CLAUDE.md, evaluation rule #6): the escalation ceiling
must NEVER lock out the legitimate user under sustained attack. This is
mechanically guaranteed, not just tested: `MitigationAction` has no
"locked" value at all — it is one of `step_up_required`,
`alt_factor_required`, or `cooldown_active`, matching the Postgres CHECK
constraint in infra/postgres/init.sql. There is no code path in this
module that can produce any other outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

from services.mitigation.app.cooldown import in_cooldown
from services.mitigation.app.escalation import should_escalate

MitigationAction = Literal["step_up_required", "alt_factor_required", "cooldown_active"]


@dataclass
class UserMitigationState:
    last_step_up_ts: Optional[datetime] = None
    failure_timestamps: list[datetime] = field(default_factory=list)

    def record_failure(self, ts: datetime) -> None:
        self.failure_timestamps.append(ts)

    def record_success(self) -> None:
        """A successful step-up/alt-factor response clears the failure
        history — the user has proven themselves, escalation resets."""
        self.failure_timestamps.clear()


def decide_action(state: UserMitigationState, now: datetime) -> MitigationAction:
    """Called whenever an alert triggers mitigation consideration for a
    user. Mutates `state.last_step_up_ts` when issuing a fresh step-up."""
    if in_cooldown(state.last_step_up_ts, now):
        return "cooldown_active"
    if should_escalate(state.failure_timestamps, now):
        return "alt_factor_required"
    state.last_step_up_ts = now
    return "step_up_required"
