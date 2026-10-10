"""1-prompt-per-5-minute pacing attacker (CLAUDE.md, "Adversarial
evaluation is required: 1 prompt / 5 min pacing"). Same deny-then-approve
capitulation structure as `low_and_slow`, but at a fixed, deliberately
evasive cadence rather than a randomized 20-40 minute range — this tests
the exact pacing CLAUDE.md calls out, separate from the benchmark's own
labelled training distribution.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from benchmark.generator.attack_profiles import RawEvent, _final_decision, _prompt_decision_pair, _rng_uuid
from benchmark.generator.latency_models import sample_benign_approve_latency_ms, sample_benign_deny_latency_ms

SLOW_PACING_GAP_SECONDS = 5 * 60
SLOW_PACING_PROMPT_COUNT_RANGE = (6, 14)  # same order of magnitude as low_and_slow


def generate_slow_pacing_attack(
    rng: np.random.Generator,
    user_id: str,
    start_ts: datetime,
    victim_device_id: str,
    victim_user_agent: str,
    victim_src_ip: str,
    victim_country: str,
) -> list[RawEvent]:
    n = int(rng.integers(*SLOW_PACING_PROMPT_COUNT_RANGE))
    attacker_ip = f"198.18.0.{int(rng.integers(1, 254))}"
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
                attack_profile="slow_pacing_adversarial",
            )
        )
        ts = ts + timedelta(milliseconds=latency_ms) + timedelta(seconds=SLOW_PACING_GAP_SECONDS)
        if is_last and decision == "approve":
            break
    return events
