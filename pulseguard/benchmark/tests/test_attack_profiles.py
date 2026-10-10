"""Verify each attack profile's pacing envelope and labelling, and the
benign-high-activity hard negative's stationarity (CLAUDE.md, "Data").
"""

from __future__ import annotations

from datetime import datetime, timezone

from benchmark.generator import attack_profiles as ap
from benchmark.generator.seed import child_rng
from pulseguard_common.time_utils import BURST_GAP_THRESHOLD_SECONDS

START_TS = datetime(2026, 1, 1, tzinfo=timezone.utc)
VICTIM_DEVICE = "victim-device-abc"
VICTIM_UA = "Mozilla/5.0 (victim)"
VICTIM_IP = "10.0.0.5"
VICTIM_COUNTRY = "US"


def _pairs(events: list[ap.RawEvent]) -> list[tuple[ap.RawEvent, ap.RawEvent]]:
    """Zips prompt/decision events back into (prompt, decision) pairs."""
    prompts = [e for e in events if e.event_type == "mfa_prompt"]
    decisions = [e for e in events if e.event_type == "mfa_decision"]
    assert len(prompts) == len(decisions)
    return list(zip(prompts, decisions))


def test_high_volume_burst_exceeds_splunk_threshold_and_stays_in_one_burst():
    rng = child_rng(42, "user1", "high_volume_burst")
    events = ap.generate_high_volume_burst(
        rng, "user1", START_TS, VICTIM_DEVICE, VICTIM_UA, VICTIM_IP, VICTIM_COUNTRY
    )
    pairs = _pairs(events)
    assert len(pairs) >= 5  # meaningful burst regardless of early-approve cutoff
    for prompt, decision in pairs:
        assert prompt.event_type == "mfa_prompt"
        assert decision.decision in {"approve", "deny"}
        assert prompt.label_attack is True
        assert prompt.attack_profile == "high_volume_burst"
    # consecutive prompt gaps stay under the burst-merge threshold
    for (p1, _), (p2, _) in zip(pairs, pairs[1:]):
        gap = (p2.ts - p1.ts).total_seconds()
        assert gap < BURST_GAP_THRESHOLD_SECONDS


def test_low_and_slow_paces_above_burst_merge_threshold():
    rng = child_rng(42, "user2", "low_and_slow")
    events = ap.generate_low_and_slow(
        rng, "user2", START_TS, VICTIM_DEVICE, VICTIM_UA, VICTIM_IP, VICTIM_COUNTRY
    )
    pairs = _pairs(events)
    assert len(pairs) >= 2
    for (p1, _), (p2, _) in zip(pairs, pairs[1:]):
        gap = (p2.ts - p1.ts).total_seconds()
        # deliberately paced ABOVE the burst-merge gap so the Splunk-style
        # 10-minute-window rule and the burst detector both miss it
        assert gap > BURST_GAP_THRESHOLD_SECONDS
        assert gap >= 20 * 60 - 1  # allow for latency offset rounding


def test_social_engineering_lure_forces_short_latency_and_approval():
    rng = child_rng(42, "user3", "social_engineering_assisted")
    events = ap.generate_social_engineering_assisted(
        rng, "user3", START_TS, VICTIM_DEVICE, VICTIM_UA, VICTIM_IP, VICTIM_COUNTRY
    )
    pairs = _pairs(events)
    decisions = [d for _, d in pairs]
    assert decisions[-1].decision == "approve"
    assert decisions[-1].decision_latency_ms <= ap.SOCIAL_ENG_LURE_INDEX_FRACTION * 0 + 2000
    # every prompt before the lure was denied
    for d in decisions[:-1]:
        assert d.decision == "deny"


def test_attacker_context_differs_from_victim_context_on_prompt():
    rng = child_rng(42, "user4", "high_volume_burst")
    events = ap.generate_high_volume_burst(
        rng, "user4", START_TS, VICTIM_DEVICE, VICTIM_UA, VICTIM_IP, VICTIM_COUNTRY
    )
    pairs = _pairs(events)
    prompt, decision = pairs[0]
    assert prompt.device_id != VICTIM_DEVICE
    assert prompt.src_ip != VICTIM_IP
    assert decision.device_id == VICTIM_DEVICE
    assert decision.src_ip == VICTIM_IP


def test_benign_high_activity_hard_negative_has_no_capitulation_signature():
    rng = child_rng(42, "poweruser", "benign_high_activity")
    events = ap.generate_benign_high_activity_session(
        rng, "poweruser", START_TS, VICTIM_DEVICE, VICTIM_UA, VICTIM_IP, VICTIM_COUNTRY
    )
    pairs = _pairs(events)
    assert len(pairs) >= ap.BENIGN_HIGH_ACTIVITY_LOGINS_PER_DAY_RANGE[0]
    for prompt, decision in pairs:
        assert decision.decision == "approve"
        assert prompt.label_attack is False
        assert decision.attack_profile is None
        # the "attacker" context on the prompt is actually the victim's own
        assert prompt.device_id == VICTIM_DEVICE
        assert prompt.src_ip == VICTIM_IP
    latencies = [d.decision_latency_ms for _, d in pairs]
    # stationary: no systematic decay across the session (unlike fatigue)
    first_half = latencies[: len(latencies) // 2]
    second_half = latencies[len(latencies) // 2 :]
    assert abs(sum(first_half) / len(first_half) - sum(second_half) / len(second_half)) < 3000


def test_benign_occasional_denial_has_exactly_one_denial_then_an_unrelated_approve():
    rng = child_rng(42, "occasional_denier", "benign_occasional_denial")
    events = ap.generate_benign_occasional_denial_session(
        rng, "occasional_denier", START_TS, VICTIM_DEVICE, VICTIM_UA, VICTIM_IP, VICTIM_COUNTRY
    )
    pairs = _pairs(events)
    assert len(pairs) == 2
    deny_prompt, deny_decision = pairs[0]
    approve_prompt, approve_decision = pairs[1]
    assert deny_decision.decision == "deny"
    assert approve_decision.decision == "approve"
    assert deny_decision.label_attack is False
    assert approve_decision.label_attack is False
    assert deny_decision.attack_profile is None
    assert approve_decision.attack_profile is None
    # the two decisions belong to separate sessions -- genuinely unrelated events
    assert deny_decision.session_id != approve_decision.session_id
    # both use the victim's own context, never an attacker-controlled origin
    assert deny_prompt.device_id == VICTIM_DEVICE
    assert approve_prompt.device_id == VICTIM_DEVICE


def test_deterministic_given_same_seed():
    rng1 = child_rng(99, "userX", "high_volume_burst")
    rng2 = child_rng(99, "userX", "high_volume_burst")
    events1 = ap.generate_high_volume_burst(
        rng1, "userX", START_TS, VICTIM_DEVICE, VICTIM_UA, VICTIM_IP, VICTIM_COUNTRY
    )
    events2 = ap.generate_high_volume_burst(
        rng2, "userX", START_TS, VICTIM_DEVICE, VICTIM_UA, VICTIM_IP, VICTIM_COUNTRY
    )
    assert [(e.ts, e.decision, e.decision_latency_ms) for e in events1] == [
        (e.ts, e.decision, e.decision_latency_ms) for e in events2
    ]
