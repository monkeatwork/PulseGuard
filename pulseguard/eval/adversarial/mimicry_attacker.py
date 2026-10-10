"""Mimicry attacker (CLAUDE.md, "an attacker who deliberately mimics the
target's own baseline rhythm"): paces each prompt using a gap sampled from
the target user's OWN historical login-gap distribution, rather than a
fixed attacker-chosen range. The point of the test is that pacing alone
gives the detector no signal — a real mimicry attacker's inter-prompt
timing is statistically indistinguishable from that user's ordinary
rhythm, by construction.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from benchmark.generator.attack_profiles import RawEvent, _final_decision, _prompt_decision_pair, _rng_uuid
from benchmark.generator.latency_models import sample_benign_approve_latency_ms, sample_benign_deny_latency_ms

MIN_GAP_SECONDS = 30.0  # floor so a sampled gap is never implausibly instant
FALLBACK_GAP_SECONDS = 300.0  # used only if a user has no usable history at all
MIMICRY_PROMPT_COUNT_RANGE = (6, 14)


def compute_historical_gaps(login_timestamps: list[datetime]) -> list[float]:
    """Inter-arrival gaps (seconds) between a user's own historical login
    events, sorted chronologically first. Needs at least 2 timestamps."""
    if len(login_timestamps) < 2:
        return []
    ordered = sorted(login_timestamps)
    return [
        gap
        for a, b in zip(ordered, ordered[1:])
        if (gap := (b - a).total_seconds()) > 0
    ]


def generate_mimicry_attack(
    rng: np.random.Generator,
    user_id: str,
    start_ts: datetime,
    victim_device_id: str,
    victim_user_agent: str,
    victim_src_ip: str,
    victim_country: str,
    historical_gap_seconds: list[float],
) -> list[RawEvent]:
    gaps = historical_gap_seconds or [FALLBACK_GAP_SECONDS]

    n = int(rng.integers(*MIMICRY_PROMPT_COUNT_RANGE))
    attacker_ip = f"198.51.100.{int(rng.integers(1, 254))}"
    attacker_device = f"unknown-device-{_rng_uuid(rng)}"
    attacker_ua = "AttackerClient/1.0"
    session_id = str(_rng_uuid(rng))

    events: list[RawEvent] = []
    ts = start_ts
    for i in range(n):
        is_last = i == n - 1
        decision = _final_decision(rng) if is_last else "deny"
        latency_ms = (
            sample_benign_approve_latency_ms(rng) if decision == "approve" else sample_benign_deny_latency_ms(rng)
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
                attack_profile="mimicry_adversarial",
            )
        )
        sampled_gap = float(rng.choice(gaps))
        gap = max(MIN_GAP_SECONDS, sampled_gap)
        ts = ts + timedelta(milliseconds=latency_ms) + timedelta(seconds=gap)
        if is_last and decision == "approve":
            break
    return events
