"""Mitigation controller tests, including the anti-DoS invariant
(CLAUDE.md, evaluation rule #6): the escalation ceiling must never lock
out the legitimate user under sustained attack.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.mitigation.app.controller import UserMitigationState, decide_action
from services.mitigation.app.cooldown import STEP_UP_COOLDOWN_SECONDS
from services.mitigation.app.escalation import ESCALATION_FAILURE_THRESHOLD

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)

VALID_ACTIONS = {"step_up_required", "alt_factor_required", "cooldown_active"}


def test_first_alert_issues_step_up():
    state = UserMitigationState()
    action = decide_action(state, T0)
    assert action == "step_up_required"
    assert state.last_step_up_ts == T0


def test_second_alert_within_cooldown_returns_cooldown_active():
    state = UserMitigationState()
    decide_action(state, T0)
    action = decide_action(state, T0 + timedelta(seconds=30))
    assert action == "cooldown_active"


def test_alert_after_cooldown_issues_a_new_step_up():
    state = UserMitigationState()
    decide_action(state, T0)
    later = T0 + timedelta(seconds=STEP_UP_COOLDOWN_SECONDS + 1)
    action = decide_action(state, later)
    assert action == "step_up_required"


def test_repeated_failures_escalate_to_alt_factor_not_lockout():
    state = UserMitigationState()
    now = T0
    for _ in range(ESCALATION_FAILURE_THRESHOLD):
        decide_action(state, now)
        state.record_failure(now)
        now += timedelta(seconds=STEP_UP_COOLDOWN_SECONDS + 1)

    action = decide_action(state, now)
    assert action == "alt_factor_required"


def test_successful_response_resets_escalation():
    state = UserMitigationState()
    now = T0
    for _ in range(ESCALATION_FAILURE_THRESHOLD):
        decide_action(state, now)
        state.record_failure(now)
        now += timedelta(seconds=STEP_UP_COOLDOWN_SECONDS + 1)

    state.record_success()
    action = decide_action(state, now)
    assert action == "step_up_required"  # back to normal, not still escalated


def test_anti_dos_invariant_sustained_attack_never_locks_out_user():
    """Simulates 500+ prompts/hour against one user (a sustained high-volume
    fatigue attack) and asserts the account status only ever reaches
    step_up_required/alt_factor_required/cooldown_active -- never a locked
    state, at any point in the simulation."""
    state = UserMitigationState()
    now = T0
    actions_seen = set()

    # ~500 prompts/hour = one prompt every ~7.2 seconds, simulated for 2 hours
    prompt_interval = timedelta(seconds=7)
    total_prompts = 1000

    for i in range(total_prompts):
        action = decide_action(state, now)
        actions_seen.add(action)
        assert action in VALID_ACTIONS  # mechanically can never be "locked"

        # Simulate every step-up attempt failing (the worst case: an
        # attacker who never has the real second factor, so every attempt
        # legitimately fails) -- this is the scenario most likely to
        # tempt an implementation into a hard lockout.
        if action == "step_up_required":
            state.record_failure(now)

        now += prompt_interval

    # the escalated state must have been reached (proving escalation logic
    # actually engaged under this sustained load, not just cooldown)
    assert "alt_factor_required" in actions_seen
    assert "locked" not in actions_seen


def test_anti_dos_invariant_holds_even_with_extremely_high_frequency():
    """A pathological case: prompts arriving faster than the cooldown
    window itself (e.g. a scripted flood), for an extended period."""
    state = UserMitigationState()
    now = T0
    for _ in range(5000):
        action = decide_action(state, now)
        assert action in VALID_ACTIONS
        if action == "step_up_required":
            state.record_failure(now)
        now += timedelta(seconds=1)  # far faster than the 5-min cooldown
