from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pulseguard_common.windows import (
    pair_prompts_and_decisions,
    segment_into_bursts,
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _prompt(offset_s: float) -> dict:
    return {"event_type": "mfa_prompt", "ts": T0 + timedelta(seconds=offset_s)}


def _decision(offset_s: float, decision: str, latency_ms: int, ingest_offset_s: float = 0.0) -> dict:
    ts = T0 + timedelta(seconds=offset_s)
    return {
        "event_type": "mfa_decision",
        "ts": ts,
        "decision": decision,
        "decision_latency_ms": latency_ms,
        "ingest_ts": ts + timedelta(seconds=ingest_offset_s),
    }


def test_pairs_prompt_and_decision_in_order():
    events = [_prompt(0), _decision(2, "approve", 2000)]
    pairs = pair_prompts_and_decisions(events)
    assert len(pairs) == 1
    assert pairs[0].decision == "approve"
    assert pairs[0].decision_latency_ms == 2000


def test_unanswered_prompt_becomes_timeout_pair():
    events = [_prompt(0), _prompt(30)]  # second prompt arrives before first is answered
    pairs = pair_prompts_and_decisions(events)
    assert len(pairs) == 2
    assert pairs[0].decision is None
    assert pairs[0].decision_latency_ms is None


def test_trailing_unanswered_prompt_is_captured():
    events = [_prompt(0), _decision(1, "deny", 1000), _prompt(10)]
    pairs = pair_prompts_and_decisions(events)
    assert len(pairs) == 2
    assert pairs[-1].decision is None


def test_segment_into_bursts_splits_on_gap_threshold():
    events = [_prompt(0), _decision(1, "deny", 1000), _prompt(60), _decision(61, "deny", 1000), _prompt(1000), _decision(1001, "approve", 1000)]
    pairs = pair_prompts_and_decisions(events)
    bursts = segment_into_bursts(pairs)
    # first two prompts are 60s apart (< 5min threshold) -> same burst
    # third prompt is 1000-60=940s later (>5min) -> new burst
    assert len(bursts) == 2
    assert len(bursts[0]) == 2
    assert len(bursts[1]) == 1


def test_segment_into_bursts_assigns_sequential_prompt_index():
    events = []
    for i in range(4):
        events.append(_prompt(i * 30))
        events.append(_decision(i * 30 + 1, "deny", 1000))
    pairs = pair_prompts_and_decisions(events)
    bursts = segment_into_bursts(pairs)
    assert len(bursts) == 1
    assert [p.prompt_index for p in bursts[0]] == [0, 1, 2, 3]


def test_segment_into_bursts_empty_input():
    assert segment_into_bursts([]) == []


def test_segment_into_bursts_is_robust_to_out_of_order_input():
    events = [_prompt(0), _decision(1, "deny", 1000), _prompt(30), _decision(31, "approve", 1000)]
    pairs = pair_prompts_and_decisions(events)
    shuffled = [pairs[1], pairs[0]]
    bursts = segment_into_bursts(shuffled)
    assert len(bursts) == 1
    assert bursts[0][0].prompt_ts < bursts[0][1].prompt_ts
