"""Labelled MFA-prompt/decision event sequence generators.

Each function returns a list of plain dicts (not yet validated
PulseGuardEvent objects — `cli.py` does that conversion) representing one
burst or session for one user. Every draw goes through a caller-supplied
`numpy.random.Generator` so the whole generator is deterministic given a
seed (see seed.py).

Three attack profiles (CLAUDE.md, "Data"):
  - high_volume_burst: many prompts in rapid succession.
  - low_and_slow: prompts paced below the 10-minute/9-prompt Splunk
    threshold, deliberately evading fixed-rate rules.
  - social_engineering_assisted: a lure event mid-burst that forces an
    artificially short latency (the victim is on a call being talked
    through the approval).

Plus benign_high_activity_session: the hard-negative case — a legitimate
power user approving many logins per day with stationary latency and no
capitulation signature. This is what makes the false-positive rate
measurement meaningful (CLAUDE.md, evaluation rule #3).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from benchmark.generator.latency_models import (
    sample_benign_approve_latency_ms,
    sample_benign_deny_latency_ms,
    sample_fatigue_latency_ms,
    sample_lure_latency_ms,
)

# --- Burst pacing --------------------------------------------------------
# Must stay consistent with the burst-boundary definition in
# pulseguard_common.time_utils (BURST_GAP_THRESHOLD_SECONDS = 5 min) so a
# high-volume burst is one burst and a low-and-slow attack is deliberately
# NOT merged into one.
HIGH_VOLUME_PROMPT_COUNT_RANGE = (10, 25)  # > Splunk's 9-in-10-min threshold
HIGH_VOLUME_GAP_SECONDS_RANGE = (15, 90)  # well under the 5-min burst-merge gap

LOW_AND_SLOW_PROMPT_COUNT_RANGE = (6, 14)
LOW_AND_SLOW_GAP_SECONDS_RANGE = (20 * 60, 40 * 60)  # 20-40 min, per DECISIONS.md

SOCIAL_ENG_PROMPT_COUNT_RANGE = (5, 15)
SOCIAL_ENG_GAP_SECONDS_RANGE = (15, 90)
SOCIAL_ENG_LURE_INDEX_FRACTION = 0.5  # lure lands roughly mid-burst

BENIGN_HIGH_ACTIVITY_LOGINS_PER_DAY_RANGE = (15, 40)
BENIGN_HIGH_ACTIVITY_GAP_SECONDS_RANGE = (5 * 60, 90 * 60)

FINAL_CAPITULATION_APPROVE_PROBABILITY = 0.85  # attack "succeeds" most of the time


def _rng_uuid(rng: np.random.Generator) -> uuid.UUID:
    """Deterministic UUID draw from an rng, given a fixed seed. `rng.bytes`
    returns a plain Python bytes object (unlike rng.integers, whose numpy
    scalar type is not accepted by uuid.UUID(int=...))."""
    return uuid.UUID(bytes=rng.bytes(16))


@dataclass
class RawEvent:
    user_id: str
    ts: datetime
    event_type: str
    src_ip: str
    device_id: str
    user_agent: str
    session_id: str
    decision: str | None = None
    decision_latency_ms: int | None = None
    geo_country: str | None = None
    label_attack: bool = False
    attack_profile: str | None = None


def _prompt_decision_pair(
    *,
    user_id: str,
    prompt_ts: datetime,
    decision: str,
    latency_ms: int,
    attacker_src_ip: str,
    attacker_device_id: str,
    attacker_user_agent: str,
    victim_src_ip: str,
    victim_device_id: str,
    victim_user_agent: str,
    session_id: str,
    geo_country: str,
    label_attack: bool,
    attack_profile: str | None,
) -> list[RawEvent]:
    """A push challenge is triggered from the login context (often the
    attacker's device/IP once credentials are compromised) and answered on
    the victim's own registered authenticator device — see DECISIONS.md
    entry for attack-profile device/geo modeling."""
    decision_ts = prompt_ts + timedelta(milliseconds=latency_ms)
    return [
        RawEvent(
            user_id=user_id,
            ts=prompt_ts,
            event_type="mfa_prompt",
            src_ip=attacker_src_ip,
            device_id=attacker_device_id,
            user_agent=attacker_user_agent,
            session_id=session_id,
            geo_country=geo_country,
            label_attack=label_attack,
            attack_profile=attack_profile,
        ),
        RawEvent(
            user_id=user_id,
            ts=decision_ts,
            event_type="mfa_decision",
            src_ip=victim_src_ip,
            device_id=victim_device_id,
            user_agent=victim_user_agent,
            session_id=session_id,
            decision=decision,
            decision_latency_ms=latency_ms,
            geo_country=geo_country,
            label_attack=label_attack,
            attack_profile=attack_profile,
        ),
    ]


def _final_decision(rng: np.random.Generator) -> str:
    return "approve" if rng.random() < FINAL_CAPITULATION_APPROVE_PROBABILITY else "deny"


def generate_high_volume_burst(
    rng: np.random.Generator,
    user_id: str,
    start_ts: datetime,
    victim_device_id: str,
    victim_user_agent: str,
    victim_src_ip: str,
    victim_country: str,
) -> list[RawEvent]:
    n = int(rng.integers(*HIGH_VOLUME_PROMPT_COUNT_RANGE))
    attacker_ip = f"198.51.100.{int(rng.integers(1, 254))}"
    attacker_device = f"unknown-device-{_rng_uuid(rng)}"
    attacker_ua = "AttackerClient/1.0"
    session_id = str(_rng_uuid(rng))

    events: list[RawEvent] = []
    ts = start_ts
    for i in range(n):
        is_last = i == n - 1
        decision = _final_decision(rng) if is_last else "deny"
        latency_ms = sample_fatigue_latency_ms(rng, i, n)
        events.extend(
            _prompt_decision_pair(
                user_id=user_id,
                prompt_ts=ts,
                decision=decision,
                latency_ms=latency_ms,
                attacker_src_ip=attacker_ip,
                attacker_device_id=attacker_device,
                attacker_user_agent=attacker_ua,
                victim_src_ip=victim_src_ip,
                victim_device_id=victim_device_id,
                victim_user_agent=victim_user_agent,
                session_id=session_id,
                geo_country=victim_country,
                label_attack=True,
                attack_profile="high_volume_burst",
            )
        )
        gap = int(rng.integers(*HIGH_VOLUME_GAP_SECONDS_RANGE))
        ts = ts + timedelta(milliseconds=latency_ms) + timedelta(seconds=gap)
        if is_last and decision == "approve":
            break
    return events


def generate_low_and_slow(
    rng: np.random.Generator,
    user_id: str,
    start_ts: datetime,
    victim_device_id: str,
    victim_user_agent: str,
    victim_src_ip: str,
    victim_country: str,
) -> list[RawEvent]:
    n = int(rng.integers(*LOW_AND_SLOW_PROMPT_COUNT_RANGE))
    attacker_ip = f"203.0.113.{int(rng.integers(1, 254))}"
    attacker_device = f"unknown-device-{_rng_uuid(rng)}"
    attacker_ua = "AttackerClient/1.0"
    session_id = str(_rng_uuid(rng))

    events: list[RawEvent] = []
    ts = start_ts
    for i in range(n):
        is_last = i == n - 1
        decision = _final_decision(rng) if is_last else "deny"
        # Pacing evades the burst-merge window, so no within-burst fatigue
        # drift is modeled here (the whole point of low-and-slow is to look
        # like isolated, unrelated benign denials).
        latency_ms = (
            sample_benign_approve_latency_ms(rng)
            if decision == "approve"
            else sample_benign_deny_latency_ms(rng)
        )
        events.extend(
            _prompt_decision_pair(
                user_id=user_id,
                prompt_ts=ts,
                decision=decision,
                latency_ms=latency_ms,
                attacker_src_ip=attacker_ip,
                attacker_device_id=attacker_device,
                attacker_user_agent=attacker_ua,
                victim_src_ip=victim_src_ip,
                victim_device_id=victim_device_id,
                victim_user_agent=victim_user_agent,
                session_id=session_id,
                geo_country=victim_country,
                label_attack=True,
                attack_profile="low_and_slow",
            )
        )
        gap = int(rng.integers(*LOW_AND_SLOW_GAP_SECONDS_RANGE))
        ts = ts + timedelta(milliseconds=latency_ms) + timedelta(seconds=gap)
        if is_last and decision == "approve":
            break
    return events


def generate_social_engineering_assisted(
    rng: np.random.Generator,
    user_id: str,
    start_ts: datetime,
    victim_device_id: str,
    victim_user_agent: str,
    victim_src_ip: str,
    victim_country: str,
) -> list[RawEvent]:
    n = int(rng.integers(*SOCIAL_ENG_PROMPT_COUNT_RANGE))
    lure_index = max(1, int(n * SOCIAL_ENG_LURE_INDEX_FRACTION))
    attacker_ip = f"192.0.2.{int(rng.integers(1, 254))}"
    attacker_device = f"unknown-device-{_rng_uuid(rng)}"
    attacker_ua = "AttackerClient/1.0"
    session_id = str(_rng_uuid(rng))

    events: list[RawEvent] = []
    ts = start_ts
    for i in range(n):
        if i == lure_index:
            decision = "approve"
            latency_ms = sample_lure_latency_ms(rng)
        elif i > lure_index:
            # Attack already succeeded at the lure point; profile ends there.
            break
        else:
            decision = "deny"
            latency_ms = sample_fatigue_latency_ms(rng, i, lure_index + 1)
        events.extend(
            _prompt_decision_pair(
                user_id=user_id,
                prompt_ts=ts,
                decision=decision,
                latency_ms=latency_ms,
                attacker_src_ip=attacker_ip,
                attacker_device_id=attacker_device,
                attacker_user_agent=attacker_ua,
                victim_src_ip=victim_src_ip,
                victim_device_id=victim_device_id,
                victim_user_agent=victim_user_agent,
                session_id=session_id,
                geo_country=victim_country,
                label_attack=True,
                attack_profile="social_engineering_assisted",
            )
        )
        gap = int(rng.integers(*SOCIAL_ENG_GAP_SECONDS_RANGE))
        ts = ts + timedelta(milliseconds=latency_ms) + timedelta(seconds=gap)
        if decision == "approve":
            break
    return events


def generate_benign_high_activity_session(
    rng: np.random.Generator,
    user_id: str,
    day_start_ts: datetime,
    victim_device_id: str,
    victim_user_agent: str,
    victim_src_ip: str,
    victim_country: str,
) -> list[RawEvent]:
    """Hard negative: a legitimate power user authenticating many times a
    day. Latency stays stationary (drawn from the same benign distribution
    every time, no decay), and virtually every prompt is approved from the
    user's own device/IP — there is no attacker-controlled prompt origin."""
    n = int(rng.integers(*BENIGN_HIGH_ACTIVITY_LOGINS_PER_DAY_RANGE))
    events: list[RawEvent] = []
    ts = day_start_ts
    for _ in range(n):
        session_id = str(_rng_uuid(rng))
        latency_ms = sample_benign_approve_latency_ms(rng)
        events.extend(
            _prompt_decision_pair(
                user_id=user_id,
                prompt_ts=ts,
                decision="approve",
                latency_ms=latency_ms,
                attacker_src_ip=victim_src_ip,
                attacker_device_id=victim_device_id,
                attacker_user_agent=victim_user_agent,
                victim_src_ip=victim_src_ip,
                victim_device_id=victim_device_id,
                victim_user_agent=victim_user_agent,
                session_id=session_id,
                geo_country=victim_country,
                label_attack=False,
                attack_profile=None,
            )
        )
        gap = int(rng.integers(*BENIGN_HIGH_ACTIVITY_GAP_SECONDS_RANGE))
        ts = ts + timedelta(milliseconds=latency_ms) + timedelta(seconds=gap)
    return events


# A single accidental denial, then an unrelated later approval -- both from
# normal benign latency distributions. See DECISIONS.md, "Major finding:
# Stage C's perfect scores exposed a systemic benchmark gap": every attack
# profile always has >=1 leading denial and generate_benign_high_activity_session
# never denies at all, making "any denial present" a perfect (and
# unrealistic) discriminator on its own. This profile closes that gap by
# giving the corpus a genuinely benign example that still contains exactly
# one denial -- capped below Elastic's own 2-denial threshold and below
# every attack profile's minimum leading-denial count, so deny_run_length
# stays a real discriminator instead of a proxy for this corpus artifact.
OCCASIONAL_DENIAL_GAP_SECONDS_RANGE = (5 * 60, 60 * 60)  # 5-60 min, deliberately
# overlapping both "fast" and "slow" attack pacing so gap alone can't
# substitute for the fix either.


def generate_benign_occasional_denial_session(
    rng: np.random.Generator,
    user_id: str,
    start_ts: datetime,
    victim_device_id: str,
    victim_user_agent: str,
    victim_src_ip: str,
    victim_country: str,
) -> list[RawEvent]:
    """Hard negative: a legitimate user denies exactly one prompt (a
    mis-tap, or a login they briefly didn't recognize as their own) and
    later approves a separate, unrelated prompt. Both decisions use the
    same normal benign latency distributions as any other legitimate
    approval/denial -- there is no fatigue coupling between the two
    events, and no attacker-controlled prompt origin."""
    session_id_1 = str(_rng_uuid(rng))
    session_id_2 = str(_rng_uuid(rng))

    deny_latency = sample_benign_deny_latency_ms(rng)
    events = _prompt_decision_pair(
        user_id=user_id,
        prompt_ts=start_ts,
        decision="deny",
        latency_ms=deny_latency,
        attacker_src_ip=victim_src_ip,
        attacker_device_id=victim_device_id,
        attacker_user_agent=victim_user_agent,
        victim_src_ip=victim_src_ip,
        victim_device_id=victim_device_id,
        victim_user_agent=victim_user_agent,
        session_id=session_id_1,
        geo_country=victim_country,
        label_attack=False,
        attack_profile=None,
    )

    gap = int(rng.integers(*OCCASIONAL_DENIAL_GAP_SECONDS_RANGE))
    approve_ts = start_ts + timedelta(milliseconds=deny_latency) + timedelta(seconds=gap)
    approve_latency = sample_benign_approve_latency_ms(rng)
    events.extend(
        _prompt_decision_pair(
            user_id=user_id,
            prompt_ts=approve_ts,
            decision="approve",
            latency_ms=approve_latency,
            attacker_src_ip=victim_src_ip,
            attacker_device_id=victim_device_id,
            attacker_user_agent=victim_user_agent,
            victim_src_ip=victim_src_ip,
            victim_device_id=victim_device_id,
            victim_user_agent=victim_user_agent,
            session_id=session_id_2,
            geo_country=victim_country,
            label_attack=False,
            attack_profile=None,
        )
    )
    return events
