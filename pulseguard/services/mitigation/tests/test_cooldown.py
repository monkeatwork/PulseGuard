from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.mitigation.app.cooldown import STEP_UP_COOLDOWN_SECONDS, in_cooldown

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_no_prior_step_up_is_not_in_cooldown():
    assert in_cooldown(None, T0) is False


def test_just_after_step_up_is_in_cooldown():
    assert in_cooldown(T0, T0 + timedelta(seconds=1)) is True


def test_just_before_cooldown_expires_is_still_in_cooldown():
    assert in_cooldown(T0, T0 + timedelta(seconds=STEP_UP_COOLDOWN_SECONDS - 1)) is True


def test_after_cooldown_expires_is_not_in_cooldown():
    assert in_cooldown(T0, T0 + timedelta(seconds=STEP_UP_COOLDOWN_SECONDS + 1)) is False
