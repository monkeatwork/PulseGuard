"""Unit tests for session_processor with in-memory fakes: the load-bearing
persist -> send -> trim ordering (REMEDIATION_TASK.md C2) and per-session
context (C3)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from pulseguard_common.sessions import SESSION_GAP_THRESHOLD_SECONDS
from services.detection_engine.app.feature_table import InMemoryBaselineStore
from services.feature_engine.app.session_processor import handle_event, rolling_median_skew_seconds

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


class RecordingBuffer:
    def __init__(self, log):
        self.log = log
        self.data: dict[str, list[dict]] = {}

    def append(self, user_id, entry):
        self.log.append("append")
        self.data.setdefault(user_id, []).append(entry)

    def load(self, user_id):
        return list(self.data.get(user_id, []))

    def replace(self, user_id, entries):
        self.log.append("trim")
        self.data[user_id] = list(entries)


def _pair(prompt_ts, decision, latency_ms, country="US", device="phone-1"):
    common = dict(geo_country=country, device_id=device, src_ip="10.0.0.5", user_agent="UA", session_id="s")
    return [
        dict(event_id=str(uuid.uuid4()), event_type="mfa_prompt", ts=prompt_ts, ingest_ts=prompt_ts, **common),
        dict(event_id=str(uuid.uuid4()), event_type="mfa_decision", ts=prompt_ts + timedelta(milliseconds=latency_ms),
             decision=decision, decision_latency_ms=latency_ms,
             ingest_ts=prompt_ts + timedelta(milliseconds=latency_ms), **common),
    ]


def test_send_happens_before_the_buffer_is_trimmed():
    """If the trim of a closed session ever moves ahead of the send, a crash
    in between silently loses events. This test fails on that reordering."""
    log: list[str] = []
    buffer = RecordingBuffer(log)
    store = InMemoryBaselineStore()

    async def send(user_id, message):
        log.append("send")

    async def run():
        for e in _pair(T0, "approve", 3000):
            await handle_event("u", e, buffer, store, send)
        log.clear()
        # a decision (its prompt not yet arrived) after the session gap: it
        # both closes the first session AND is a decision point to score
        late = _pair(T0 + timedelta(seconds=SESSION_GAP_THRESHOLD_SECONDS + 600), "approve", 3000)
        await handle_event("u", late[1], buffer, store, send)

    asyncio.run(run())
    assert log.index("append") < log.index("send") < log.index("trim")


def test_a_failed_send_leaves_the_buffer_untrimmed():
    log: list[str] = []
    buffer = RecordingBuffer(log)
    store = InMemoryBaselineStore()

    async def ok(user_id, message):
        pass

    async def boom(user_id, message):
        raise ConnectionError("broker down")

    async def run():
        for e in _pair(T0, "approve", 3000):
            await handle_event("u", e, buffer, store, ok)
        later = _pair(T0 + timedelta(seconds=SESSION_GAP_THRESHOLD_SECONDS + 600), "approve", 3000)
        with pytest.raises(ConnectionError):
            await handle_event("u", later[1], buffer, store, boom)

    asyncio.run(run())
    assert "trim" not in log
    assert len(buffer.data["u"]) == 3  # nothing lost; the old session is still there


def test_each_session_uses_its_own_geo_and_device_context():
    """REMEDIATION_TASK.md C3: two sessions for one user, each with its own
    geo/device, must each be featurised with their own context."""
    buffer = RecordingBuffer([])
    store = InMemoryBaselineStore()
    sent = []

    async def send(user_id, message):
        sent.append(message)

    first = _pair(T0, "approve", 3000, country="US", device="phone-1")
    second = _pair(T0 + timedelta(hours=3), "approve", 3000, country="FR", device="phone-2")

    async def run():
        for e in first + second:
            await handle_event("u", e, buffer, store, send)

    asyncio.run(run())
    assert sent[0]["sequence"][-1]["device_id"] == "phone-1"
    assert sent[1]["sequence"][-1]["device_id"] == "phone-2"
    # session 2 is scored after session 1 was committed: FR/phone-2 are new to this user
    assert sent[1]["feature_vector"]["geo_novelty"] is True
    assert sent[1]["feature_vector"]["device_novelty"] is True


def test_out_of_order_decision_is_scored_on_the_session_in_timestamp_order():
    buffer = RecordingBuffer([])
    store = InMemoryBaselineStore()
    sent = []

    async def send(user_id, message):
        sent.append(message)

    p1 = _pair(T0, "deny", 4000)
    p2 = _pair(T0 + timedelta(seconds=30), "approve", 1000)

    async def run():
        for e in [p1[0], p2[0], p2[1], p1[1]]:  # p1's decision arrives last
            await handle_event("u", e, buffer, store, send)

    asyncio.run(run())
    assert len(sent) == 2
    assert sent[-1]["decision_index"] == 0  # its own (earlier) position in the session
    assert sent[-1]["feature_vector"]["n_prompts"] == 1


def test_rolling_median_skew_tracks_a_constant_collector_delay():
    events = []
    for i in range(5):
        ts = T0 + timedelta(seconds=10 * i)
        events.append({"ts": ts, "ingest_ts": ts + timedelta(seconds=7)})
    assert rolling_median_skew_seconds(events) == pytest.approx(7.0)
    assert rolling_median_skew_seconds([{"ts": T0}]) == 0.0
