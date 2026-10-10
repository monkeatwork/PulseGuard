"""L3 Faust stream app: consumes `pulseguard.events.raw`, buffers per-user
prompt/decision events, finalizes bursts once the out-of-order grace window
has elapsed, computes each burst's feature vector against Redis-backed
baselines, and produces the result to `pulseguard.events.enriched`.

This module is thin Kafka/Redis wiring only — every actual computation is
delegated to the pure functions in windows.py/enrichment.py, which carry
their own unit tests. See DECISIONS.md, "Phase 3 streaming integration test
scope", for why this module's live Kafka-consumption behavior is exercised
through `docker compose up` rather than a Testcontainers+Faust-worker test:
Faust's own consumer-group/rebalancing correctness is the framework's
concern, not something this project needs to re-prove.

Known simplification: when a timer tick finalizes more than one user's
burst at once, each finalized burst uses the *last* raw event in that
user's buffer for geo/device context, rather than the context matching
that specific burst. In practice a burst's grace window (5s) is far
shorter than the timer interval (1s) times the number of concurrent
bursts a single user can have, so this only matters for the rare case of
multiple ready bursts for the same user in the same tick — flagged here
rather than hidden.
"""

from __future__ import annotations

import json
import os
from datetime import datetime

import faust
import redis as redis_lib

from pulseguard_common.event_schema import PulseGuardEvent
from pulseguard_common.redis_keys import BURST_KEY_TTL_SECONDS, burst_current_key
from pulseguard_common.time_utils import utcnow
from pulseguard_common.baseline_store import RedisBaselineStore
from pulseguard_common.enrichment import CohortBaselineProvider, enrich_burst
from pulseguard_common.windows import (
    is_burst_finalizable,
    pair_prompts_and_decisions,
    segment_into_bursts,
)

KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "redpanda:9092")
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
FINALIZE_TIMER_INTERVAL_SECONDS = 1.0

# Set of user_ids currently holding a non-empty pending buffer, so the
# finalize timer knows who to check without scanning the whole keyspace.
PENDING_USERS_KEY = "pg:burst:pending_users"

app = faust.App(
    "pulseguard-feature-engine",
    broker=f"kafka://{KAFKA_BOOTSTRAP_SERVERS}",
    value_serializer="raw",
)

raw_topic = app.topic("pulseguard.events.raw")
enriched_topic = app.topic("pulseguard.events.enriched")

# The per-user buffer of events awaiting burst finalization lives in REDIS,
# not a Faust Table. This matters, and was learned the hard way: Faust
# forbids writing to a Table outside stream iteration ("Cannot modify table
# key from outside of stream iteration"), because a table write must be
# tied to the source partition/offset being processed for changelog
# correctness. Our finalization is inherently time-driven (a burst is ready
# once its grace window elapses, whether or not a new event arrives), so it
# runs on a timer -- which a Faust Table structurally cannot support.
#
# Redis was in fact the original Phase 0 design for this buffer
# (`pg:burst:{user_id}:current`, TTL 15min -- see redis_keys.py); using a
# Faust Table was an undocumented drift from that decision, and it is what
# broke. As a bonus this removes the table's changelog topic entirely,
# along with Faust's co-partitioning constraint that caused the earlier
# PartitionsMismatch crash-loop.
_baseline_store: RedisBaselineStore | None = None
_redis_client: redis_lib.Redis | None = None


def get_redis() -> redis_lib.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis_lib.Redis(host=REDIS_HOST, port=REDIS_PORT)
    return _redis_client


def get_baseline_store() -> RedisBaselineStore:
    global _baseline_store
    if _baseline_store is None:
        _baseline_store = RedisBaselineStore(get_redis())
    return _baseline_store


def _encode_buffer_entry(entry: dict) -> str:
    """datetimes aren't JSON-serializable; store them as ISO strings."""
    encoded = dict(entry)
    encoded["ts"] = entry["ts"].isoformat()
    encoded["ingest_ts"] = entry["ingest_ts"].isoformat() if entry.get("ingest_ts") else None
    return json.dumps(encoded)


def _decode_buffer_entry(raw: bytes | str) -> dict:
    decoded = json.loads(raw)
    decoded["ts"] = datetime.fromisoformat(decoded["ts"])
    decoded["ingest_ts"] = (
        datetime.fromisoformat(decoded["ingest_ts"]) if decoded.get("ingest_ts") else None
    )
    return decoded


def _encode_enriched_message(message: dict) -> bytes:
    """The app is configured with `value_serializer="raw"`, so Faust hands
    the value straight to aiokafka without serializing it -- producing a
    dict raises "a bytes-like object is required, not 'dict'". Raw is the
    right choice for the consumer side (the raw topic carries pydantic's
    own JSON, and live_scorer.py does its own `json.loads`), so the
    producer serializes explicitly here instead.

    `default=str` is a deliberate safety net: the feature vector is plain
    floats/bools today, but any datetime or numpy scalar that later leaks
    into it would otherwise crash the finalize timer -- and a crashed timer
    silently stops every burst in the system from ever being scored.
    """
    return json.dumps(message, default=str).encode("utf-8")


def event_to_raw_dict(event: PulseGuardEvent) -> dict:
    return {
        "event_type": event.event_type.value,
        "ts": event.ts,
        "decision": event.decision.value if event.decision else None,
        "decision_latency_ms": event.decision_latency_ms,
        "ingest_ts": event.ingest_ts,
        "geo_country": event.geo.country if event.geo else None,
        "device_id": event.device_id,
        "session_id": event.session_id,
    }


@app.agent(raw_topic)
async def process_events(events):
    redis_client = get_redis()
    async for raw_value in events:
        event = PulseGuardEvent.model_validate_json(raw_value)
        key = burst_current_key(event.user_id)
        pipe = redis_client.pipeline()
        pipe.rpush(key, _encode_buffer_entry(event_to_raw_dict(event)))
        pipe.expire(key, BURST_KEY_TTL_SECONDS)
        pipe.sadd(PENDING_USERS_KEY, event.user_id)
        pipe.execute()


def _serialize_sequence(raw_events: list[dict]) -> list[dict]:
    """The raw per-event sequence Stage C needs (sequence_dataset.py), sent
    alongside the aggregate feature vector Stage A/B need -- so a single
    enriched message carries everything the live detection worker requires
    without a second Kafka round trip."""
    return [
        {
            "event_type": e["event_type"],
            "ts": e["ts"].isoformat() if hasattr(e["ts"], "isoformat") else e["ts"],
            "decision": e.get("decision"),
            "decision_latency_ms": e.get("decision_latency_ms"),
        }
        for e in sorted(raw_events, key=lambda e: e["ts"])
    ]


def finalize_ready_bursts_for_user(
    user_id: str, buffer: list[dict], now, store: RedisBaselineStore
) -> tuple[list[dict], list[dict]]:
    """Pure-ish helper (only the store is stateful) so the finalization
    logic can be unit-tested without a running Faust app. Returns
    (enriched_messages, remaining_buffer). Each enriched message carries
    the aggregate feature vector (Stage A/B input), the raw event sequence
    (Stage C input), and the session_id an Alert row should be linked to.
    """
    if not buffer:
        return [], []

    pairs = pair_prompts_and_decisions(buffer)
    bursts = segment_into_bursts(pairs)
    last_event = buffer[-1]

    enriched_messages = []
    remaining_buffer = []
    for burst in bursts:
        burst_ts = {p.prompt_ts for p in burst} | {p.decision_ts for p in burst if p.decision_ts}
        burst_raw_events = [e for e in buffer if e["ts"] in burst_ts]

        if is_burst_finalizable(burst, now):
            vector = enrich_burst(
                user_id,
                burst,
                last_event.get("geo_country"),
                last_event.get("device_id", "unknown"),
                store,
                CohortBaselineProvider(),
            )
            session_id = next(
                (e.get("session_id") for e in reversed(burst_raw_events) if e.get("session_id")),
                None,
            )
            enriched_messages.append(
                {
                    "feature_vector": vector.as_dict(),
                    "session_id": session_id,
                    "sequence": _serialize_sequence(burst_raw_events),
                }
            )
        else:
            remaining_buffer.extend(burst_raw_events)

    return enriched_messages, remaining_buffer


@app.timer(interval=FINALIZE_TIMER_INTERVAL_SECONDS)
async def finalize_ready_bursts():
    """Time-driven, not event-driven: a burst becomes ready once its grace
    window elapses, whether or not another event ever arrives for that
    user. This is why the buffer must live in Redis rather than a Faust
    Table -- see the module-level comment."""
    redis_client = get_redis()
    store = get_baseline_store()
    now = utcnow()

    for raw_user_id in list(redis_client.smembers(PENDING_USERS_KEY)):
        user_id = raw_user_id.decode() if isinstance(raw_user_id, bytes) else raw_user_id
        key = burst_current_key(user_id)
        buffer = [_decode_buffer_entry(raw) for raw in redis_client.lrange(key, 0, -1)]
        if not buffer:
            redis_client.srem(PENDING_USERS_KEY, user_id)
            continue

        messages, remaining = finalize_ready_bursts_for_user(user_id, buffer, now, store)
        for message in messages:
            await enriched_topic.send(value=_encode_enriched_message(message))

        pipe = redis_client.pipeline()
        pipe.delete(key)
        if remaining:
            pipe.rpush(key, *[_encode_buffer_entry(e) for e in remaining])
            pipe.expire(key, BURST_KEY_TTL_SECONDS)
        else:
            pipe.srem(PENDING_USERS_KEY, user_id)
        pipe.execute()
