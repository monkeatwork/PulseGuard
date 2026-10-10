"""Tests the live feature engine's per-event path (session_processor.handle_event)
against a REAL Redis buffer (Testcontainers + streaming_app.RedisBuffer), but
without a Faust worker or Kafka broker -- see DECISIONS.md, "Phase 3
streaming integration test scope". Kafka consumption itself is exercised by
the end-to-end run (`./run.sh` plus a replay).

Includes the per-decision scoring-latency check that stands in for CLAUDE.md's
"single-digit-millisecond scoring" budget on the feature side: session-level
aggregation recomputes the session-so-far on every decision, so this is
where the extra cost of REMEDIATION_TASK.md A2 would show up.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import redis as redis_lib
from testcontainers.community.redis import RedisContainer

from pulseguard_common.baseline_store import RedisBaselineStore
from services.feature_engine.app.session_processor import handle_event
from services.feature_engine.app.streaming_app import RedisBuffer

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def redis_client():
    with RedisContainer("redis:7.2-alpine") as container:
        client = redis_lib.Redis(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(6379)),
        )
        yield client


@pytest.fixture(autouse=True)
def _flush_between_tests(redis_client):
    redis_client.flushall()
    yield


def _pair(user, prompt_ts, decision, latency_ms, session_id="sess-1"):
    decision_ts = prompt_ts + timedelta(milliseconds=latency_ms)
    common = dict(geo_country="US", device_id="victim-phone", src_ip="10.0.0.5", user_agent="UA", session_id=session_id)
    return [
        dict(event_id=str(uuid.uuid4()), event_type="mfa_prompt", ts=prompt_ts, decision=None,
             decision_latency_ms=None, ingest_ts=prompt_ts, **common),
        dict(event_id=str(uuid.uuid4()), event_type="mfa_decision", ts=decision_ts, decision=decision,
             decision_latency_ms=latency_ms, ingest_ts=decision_ts, **common),
    ]


async def _feed(entries, user, buffer, store):
    sent = []

    async def send(user_id, message):
        sent.append(message)

    for entry in entries:
        await handle_event(user, entry, buffer, store, send)
    return sent


def test_every_decision_emits_one_session_prefix_message(redis_client):
    store = RedisBaselineStore(redis_client)
    buffer = RedisBuffer(redis_client)
    entries = []
    for i in range(3):
        entries += _pair("u1", T0 + timedelta(seconds=30 * i), "deny" if i < 2 else "approve", 4000 - 1000 * i)
    sent = asyncio.run(_feed(entries, "u1", buffer, store))

    assert [m["decision_index"] for m in sent] == [0, 1, 2]
    assert [m["feature_vector"]["n_prompts"] for m in sent] == [1, 2, 3]
    final = sent[-1]
    assert final["feature_vector"]["capitulation_flag"] is True
    assert final["feature_vector"]["latency_drift_slope"] < 0
    assert len(final["sequence"]) == 6
    assert len({m["episode_id"] for m in sent}) == 1  # one episode id per session
    # the open session stays buffered (not trimmed) until it closes
    assert len(buffer.load("u1")) == 6


def test_replayed_low_and_slow_episode_has_valid_slope_and_whole_deny_run(redis_client):
    """REMEDIATION_TASK.md A1 verification on the live path: prompts 25
    minutes apart (beyond the old 15-minute TTL and 5-minute gap) still form
    one session, so the final decision point carries the whole deny run and
    a computable latency_drift_slope."""
    store = RedisBaselineStore(redis_client)
    buffer = RedisBuffer(redis_client)
    entries = []
    for i in range(5):
        entries += _pair("slow", T0 + timedelta(minutes=25 * i), "deny" if i < 4 else "approve", 5000 - 700 * i)
    sent = asyncio.run(_feed(entries, "slow", buffer, store))

    final = sent[-1]["feature_vector"]
    assert final["latency_drift_slope_valid"] is True
    assert final["deny_run_length"] == 4
    assert final["n_prompts"] == 5
    assert final["capitulation_flag"] is True


def test_a_gap_beyond_the_session_threshold_closes_and_commits_the_old_session(redis_client):
    store = RedisBaselineStore(redis_client)
    buffer = RedisBuffer(redis_client)
    first = _pair("u2", T0, "approve", 3000)
    second = _pair("u2", T0 + timedelta(hours=3), "approve", 3000)
    sent = asyncio.run(_feed(first + second, "u2", buffer, store))

    assert len({m["episode_id"] for m in sent}) == 2
    assert sent[-1]["feature_vector"]["n_prompts"] == 1
    # the first session's approval reached the baseline when it closed
    assert store.load_latency("u2").event_count == 1
    assert len(buffer.load("u2")) == 2  # only the open session remains


def test_per_decision_feature_latency_stays_within_budget(redis_client):
    """Times handle_event over a 40-prompt session (longer than any
    generated attack) against real Redis: the median per-decision cost of
    re-featurising the session-so-far must stay in single-digit ms."""
    store = RedisBaselineStore(redis_client)
    buffer = RedisBuffer(redis_client)
    entries = []
    for i in range(40):
        entries += _pair("fast", T0 + timedelta(seconds=20 * i), "deny", 3000)

    timings = []

    async def run():
        async def send(user_id, message):
            pass

        for entry in entries:
            start = time.perf_counter()
            await handle_event("fast", entry, buffer, store, send)
            if entry["event_type"] == "mfa_decision":
                timings.append(time.perf_counter() - start)

    asyncio.run(run())
    timings.sort()
    median_ms = timings[len(timings) // 2] * 1000
    assert median_ms < 10.0, f"median per-decision feature latency {median_ms:.2f}ms"
