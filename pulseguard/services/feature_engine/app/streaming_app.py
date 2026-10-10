"""L3 Faust stream app: consumes `pulseguard.events.raw`, keeps each user's
open MFA session in Redis, and on every `mfa_decision` produces the
session-so-far's feature vector (plus the raw sequence Stage C needs) to
`pulseguard.events.enriched`.

This module is thin Kafka/Redis wiring only. The per-event logic, including
the load-bearing persist -> send -> trim ordering, lives in
session_processor.py; feature maths lives in pulseguard_common.

Scoring is event-driven, not timer-driven: a decision is featurised the
moment it arrives, which is what in-band mitigation needs (the old design
waited for a burst to go quiet before scoring it). The only timer left
closes sessions for users who have been silent longer than the session gap,
committing them to the baselines.

The buffer lives in Redis, not a Faust Table: Faust forbids writing to a
Table outside stream iteration, and the idle-close timer must write
(DECISIONS.md, 2026-09-21). With no Table there is also no co-partitioning
constraint, so `pulseguard.events.raw` can have several partitions keyed by
user_id (REMEDIATION_TASK.md C4).
"""

from __future__ import annotations

import os
import time

import faust
import redis as redis_lib

from pulseguard_common.baseline_store import RedisBaselineStore
from pulseguard_common.event_schema import PulseGuardEvent
from pulseguard_common.redis_keys import BURST_KEY_TTL_SECONDS, burst_current_key
from pulseguard_common.sessions import SESSION_GAP_THRESHOLD_SECONDS
from services.feature_engine.app.session_processor import (
    close_idle_user,
    decode_entry,
    encode_entry,
    entry_from_event,
    handle_event,
)

KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
IDLE_CLOSE_TIMER_INTERVAL_SECONDS = 30.0

# Sorted set: user_id -> wall-clock time of that user's last event arrival.
# Processing time, deliberately: replayed historical events carry old IdP
# timestamps, and closing their sessions by event time would close them the
# instant they arrive.
ACTIVE_USERS_KEY = "pg:session:active_users"

app = faust.App(
    "pulseguard-feature-engine",
    broker=f"kafka://{KAFKA_BOOTSTRAP_SERVERS}",
    value_serializer="raw",
    topic_allow_declare=False,  # topics are created up front by the kafka-init job
)

raw_topic = app.topic("pulseguard.events.raw")
enriched_topic = app.topic("pulseguard.events.enriched")

_redis_client: redis_lib.Redis | None = None
_store: RedisBaselineStore | None = None


def get_redis() -> redis_lib.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis_lib.Redis(host=REDIS_HOST, port=REDIS_PORT)
    return _redis_client


def get_store() -> RedisBaselineStore:
    global _store
    if _store is None:
        _store = RedisBaselineStore(get_redis())
    return _store


class RedisBuffer:
    """BufferIO over a Redis list per user."""

    def __init__(self, client: redis_lib.Redis):
        self._r = client

    def append(self, user_id: str, entry: dict) -> None:
        key = burst_current_key(user_id)
        pipe = self._r.pipeline()
        pipe.rpush(key, encode_entry(entry))
        pipe.expire(key, BURST_KEY_TTL_SECONDS)
        pipe.zadd(ACTIVE_USERS_KEY, {user_id: time.time()})
        pipe.execute()

    def load(self, user_id: str) -> list[dict]:
        return [decode_entry(raw) for raw in self._r.lrange(burst_current_key(user_id), 0, -1)]

    def replace(self, user_id: str, entries: list[dict]) -> None:
        key = burst_current_key(user_id)
        pipe = self._r.pipeline()
        pipe.delete(key)
        if entries:
            pipe.rpush(key, *[encode_entry(e) for e in entries])
            pipe.expire(key, BURST_KEY_TTL_SECONDS)
        else:
            pipe.zrem(ACTIVE_USERS_KEY, user_id)
        pipe.execute()


def encode_message(message: dict) -> bytes:
    """`value_serializer="raw"` hands values straight to the producer, so
    serialise explicitly. `default=str` keeps a stray datetime/numpy scalar
    from crashing the agent."""
    import json

    return json.dumps(message, default=str).encode("utf-8")


async def _send(user_id: str, message: dict) -> None:
    await enriched_topic.send(key=user_id.encode("utf-8"), value=encode_message(message))


@app.agent(raw_topic)
async def process_events(events):
    buffer = RedisBuffer(get_redis())
    store = get_store()
    async for raw_value in events:
        event = PulseGuardEvent.model_validate_json(raw_value)
        await handle_event(event.user_id, entry_from_event(event), buffer, store, _send)


@app.timer(interval=IDLE_CLOSE_TIMER_INTERVAL_SECONDS)
async def close_idle_sessions():
    client = get_redis()
    cutoff = time.time() - SESSION_GAP_THRESHOLD_SECONDS
    buffer = RedisBuffer(client)
    for raw in client.zrangebyscore(ACTIVE_USERS_KEY, 0, cutoff):
        user_id = raw.decode() if isinstance(raw, bytes) else raw
        close_idle_user(user_id, buffer, get_store())
