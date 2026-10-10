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
    decisions = [d.decision for _, d in pairs]
    for prompt, decision in pairs:
        assert decision.decision in {"approve", "deny"}
        assert prompt.label_attack is False
        assert decision.attack_profile is None
        # the "attacker" context on the prompt is actually the victim's own
        assert prompt.device_id == VICTIM_DEVICE
        assert prompt.src_ip == VICTIM_IP
    # a denial is never followed by another denial: no deny run of >= 2
    for first, second in zip(decisions, decisions[1:]):
        assert not (first == "deny" and second == "deny")
    approve_latencies = [d.decision_latency_ms for _, d in pairs if d.decision == "approve"]
    # stationary: no systematic decay across the session (unlike fatigue)
    first_half = approve_latencies[: len(approve_latencies) // 2]
    second_half = approve_latencies[len(approve_latencies) // 2 :]
    assert abs(sum(first_half) / len(first_half) - sum(second_half) / len(second_half)) < 3000


def test_benign_high_activity_contains_genuine_denials_across_users():
    """REMEDIATION_TASK.md A3: the high-activity hard negative must be able to
    contain a denial followed by a legitimate approval, so "any denial" is no
    longer a free shortcut for separating the classes."""
    found = 0
    for i in range(40):
        rng = child_rng(42, f"poweruser{i}", "benign_high_activity")
        events = ap.generate_benign_high_activity_session(
            rng, f"poweruser{i}", START_TS, VICTIM_DEVICE, VICTIM_UA, VICTIM_IP, VICTIM_COUNTRY
        )
        decisions = [d.decision for _, d in _pairs(events)]
        for first, second in zip(decisions, decisions[1:]):
            if first == "deny":
                assert second == "approve"
                found += 1
        assert all(e.label_attack is False for e in events)
    assert found > 0


def test_benign_occasional_denial_has_exactly_one_denial_then_an_unrelated_approve():
    rng = child_rng(42, "occasional_denier", "benign_occasional_denial")
    events = ap.generate_benign_occasional_denial_session(
        rng, "occasional_denier", START_TS, VICTIM_DEVICE, VICTIM_UA, VICTIM_IP, VICTIM_COUNTRY
    )
    pairs = _pairs(events)
    assert 2 <= len(pairs) <= 2 + ap.OCCASIONAL_DENIAL_EXTRA_APPROVALS_RANGE[1] - 1
    assert [d.decision for _, d in pairs].count("deny") == 1
    assert all(d.decision == "approve" for _, d in pairs[1:])
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


def test_session_gap_and_buffer_ttl_outlast_low_and_slow_pacing():
    """REMEDIATION_TASK.md A1 regression guard: a low-and-slow attack's
    widest inter-prompt gap must fit inside one session, and the live
    buffer must not expire before the next prompt arrives."""
    from pulseguard_common.redis_keys import BURST_KEY_TTL_SECONDS
    from pulseguard_common.sessions import SESSION_GAP_THRESHOLD_SECONDS

    widest_gap = ap.LOW_AND_SLOW_GAP_SECONDS_RANGE[1]
    assert SESSION_GAP_THRESHOLD_SECONDS > widest_gap
    assert BURST_KEY_TTL_SECONDS > SESSION_GAP_THRESHOLD_SECONDS
