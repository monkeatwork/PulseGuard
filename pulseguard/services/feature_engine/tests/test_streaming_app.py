"""Tests the finalization logic streaming_app.py's timer calls, against a
real Redis backend (Testcontainers) but without a running Faust worker or
Kafka broker — see DECISIONS.md, "Phase 3 streaming integration test
scope", for why full Kafka consumption is exercised via `docker compose up`
rather than here.

Includes a throughput check standing in for the Phase 3 gate's "p99 < 200ms
enrichment latency on a 10k-event burst": since we cannot measure live
per-event Kafka pipeline latency without a running broker+worker in a unit
test, this measures the CPU-bound part (pairing/segmentation/enrichment)
directly, which is where that budget is actually spent.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import redis as redis_lib
import pytest
from testcontainers.community.redis import RedisContainer

from pulseguard_common.baseline_store import RedisBaselineStore
from services.feature_engine.app.streaming_app import finalize_ready_bursts_for_user

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


def _make_buffer(n_pairs: int, gap_seconds: float = 1.0, session_id: str = "session-abc") -> list[dict]:
    buffer = []
    ts = T0
    for i in range(n_pairs):
        prompt_ts = ts
        decision_ts = prompt_ts + timedelta(milliseconds=500)
        buffer.append({
            "event_type": "mfa_prompt", "ts": prompt_ts, "geo_country": "US", "device_id": "d1",
            "session_id": session_id,
        })
        buffer.append(
            {
                "event_type": "mfa_decision", "ts": decision_ts,
                "decision": "deny" if i < n_pairs - 1 else "approve",
                "decision_latency_ms": 5000 - i * 5 if i < n_pairs - 1 else 500,
                "ingest_ts": decision_ts, "geo_country": "US", "device_id": "d1",
                "session_id": session_id,
            }
        )
        ts = decision_ts + timedelta(seconds=gap_seconds)
    return buffer


def test_burst_within_grace_window_is_not_finalized_yet(redis_client):
    store = RedisBaselineStore(redis_client)
    buffer = _make_buffer(3)
    last_prompt_ts = buffer[-2]["ts"]
    now = last_prompt_ts + timedelta(seconds=1)  # well within the 5s grace window

    messages, remaining = finalize_ready_bursts_for_user("user1", buffer, now, store)
    assert messages == []
    assert len(remaining) == len(buffer)


def test_burst_past_grace_window_is_finalized(redis_client):
    store = RedisBaselineStore(redis_client)
    buffer = _make_buffer(3)
    last_prompt_ts = buffer[-2]["ts"]
    now = last_prompt_ts + timedelta(seconds=10)  # past the 5s grace window

    messages, remaining = finalize_ready_bursts_for_user("user1", buffer, now, store)
    assert len(messages) == 1
    assert remaining == []
    assert messages[0]["feature_vector"]["n_prompts"] == 3
    assert messages[0]["feature_vector"]["capitulation_flag"] is True
    assert messages[0]["session_id"] == "session-abc"
    assert len(messages[0]["sequence"]) == 6  # 3 prompts + 3 decisions


def test_empty_buffer_finalizes_to_nothing(redis_client):
    store = RedisBaselineStore(redis_client)
    messages, remaining = finalize_ready_bursts_for_user("user1", [], T0, store)
    assert messages == []
    assert remaining == []


def test_enrichment_throughput_on_a_10k_event_burst(redis_client):
    """5000 prompt/decision pairs = 10,000 raw canonical events, all paced
    1s apart (one continuous burst). Stands in for the Phase 3 gate's
    enrichment-latency budget -- see module docstring."""
    store = RedisBaselineStore(redis_client)
    buffer = _make_buffer(5000, gap_seconds=1.0)
    assert len(buffer) == 10_000

    last_prompt_ts = buffer[-2]["ts"]
    now = last_prompt_ts + timedelta(seconds=10)

    start = time.perf_counter()
    messages, remaining = finalize_ready_bursts_for_user("user1", buffer, now, store)
    elapsed = time.perf_counter() - start

    assert len(messages) == 1
    assert remaining == []
    assert elapsed < 2.0, f"enrichment took {elapsed:.3f}s for 10k events, expected well under 2s"

    for key, value in messages[0]["feature_vector"].items():
        if isinstance(value, float):
            assert value == value, f"{key} is NaN"
