"""Per-user session buffer logic for the live feature engine, kept free of
Faust so it can be unit-tested directly (CLAUDE.md, "Feature computation is
pure and unit-testable in isolation from the stream").

On every incoming event for a user:
  1. the event is APPENDED to that user's Redis buffer (durable first);
  2. the buffer is split into sessions (sessions.py); every session except
     the newest is closed;
  3. if the event is an `mfa_decision` in the open session, the session up
     to that decision is featurised and an enriched message is SENT;
  4. only then are closed sessions committed to the baselines and TRIMMED
     from the buffer.

The 3-before-4 ordering is load-bearing (REMEDIATION_TASK.md C2): if the
process dies between the send and the trim, the buffer still holds the
events, so nothing is lost -- at worst a decision point is scored twice,
and the detection engine upserts alerts by episode id, so a duplicate
score is idempotent. Trimming first would turn that crash into silent
data loss. test_session_processor.py fails if the order changes.
"""

from __future__ import annotations

import json
from datetime import datetime
from statistics import median
from typing import Awaitable, Callable, Optional, Protocol

from pulseguard_common.enrichment import CohortBaselineProvider, commit_baselines, compute_features
from pulseguard_common.sessions import (
    decision_point_prefixes,
    episode_id,
    segment_events_into_sessions,
    session_context,
    session_pairs,
)


class BufferIO(Protocol):
    def append(self, user_id: str, entry: dict) -> None: ...
    def load(self, user_id: str) -> list[dict]: ...
    def replace(self, user_id: str, entries: list[dict]) -> None: ...


Sender = Callable[[str, dict], Awaitable[None]]


def encode_entry(entry: dict) -> str:
    encoded = dict(entry)
    for key in ("ts", "ingest_ts"):
        value = encoded.get(key)
        encoded[key] = value.isoformat() if isinstance(value, datetime) else value
    return json.dumps(encoded)


def decode_entry(raw: bytes | str) -> dict:
    decoded = json.loads(raw)
    for key in ("ts", "ingest_ts"):
        if decoded.get(key):
            decoded[key] = datetime.fromisoformat(decoded[key])
    return decoded


def rolling_median_skew_seconds(events: list[dict]) -> float:
    """Median (ingest_ts - ts) over the session's events that carry both --
    the per-user reference that `latency_drift_slope`'s clock-skew exclusion
    compares each point against (DECISIONS.md, "latency_drift_slope edge
    cases"). 0.0 when nothing carries an ingest timestamp."""
    skews = [
        (e["ingest_ts"] - e["ts"]).total_seconds()
        for e in events
        if isinstance(e.get("ingest_ts"), datetime) and isinstance(e.get("ts"), datetime)
    ]
    return median(skews) if skews else 0.0


def _wire_event(e: dict) -> dict:
    return {
        "event_id": e.get("event_id"),
        "event_type": e["event_type"],
        "ts": e["ts"].isoformat(),
        "decision": e.get("decision"),
        "decision_latency_ms": e.get("decision_latency_ms"),
        "src_ip": e.get("src_ip"),
        "device_id": e.get("device_id"),
        "user_agent": e.get("user_agent"),
        "geo_country": e.get("geo_country"),
        "session_id": e.get("session_id"),
        "ingest_ts": e["ingest_ts"].isoformat() if isinstance(e.get("ingest_ts"), datetime) else None,
    }


def build_enriched_message(user_id: str, session: list[dict], prefix: list[dict], decision_index: int, store) -> dict:
    country, device_id = session_context(prefix)
    vector = compute_features(
        user_id,
        session_pairs(prefix),
        country,
        device_id,
        store,
        CohortBaselineProvider(),
        rolling_median_skew_seconds(prefix),
    )
    trigger = prefix[-1]
    return {
        "feature_vector": vector.as_dict(),
        "episode_id": episode_id(user_id, session),
        "session_id": trigger.get("session_id"),
        "decision_index": decision_index,
        "trigger_event_id": trigger.get("event_id"),
        "sequence": [_wire_event(e) for e in sorted(prefix, key=lambda e: e["ts"])],
    }


def _close_sessions(user_id: str, sessions: list[list[dict]], store) -> None:
    for session in sessions:
        country, device_id = session_context(session)
        commit_baselines(user_id, session_pairs(session), country, device_id, store)


async def handle_event(user_id: str, entry: dict, buffer: BufferIO, store, send: Sender) -> list[dict]:
    """Steps 1-4 of the module docstring for one event. Returns the
    enriched messages it sent."""
    buffer.append(user_id, entry)  # 1. durable first

    sessions = segment_events_into_sessions(buffer.load(user_id))
    if not sessions:
        return []
    closed, open_session = sessions[:-1], sessions[-1]

    # 2. score the decision point this event creates. A decision that lands
    # in an already-closed session (arrived more than a session gap late)
    # is not re-scored: it still reaches the baselines when that session
    # is committed below.
    messages: list[dict] = []
    if entry.get("event_type") == "mfa_decision":
        for decision_index, prefix in decision_point_prefixes(open_session):
            if prefix[-1].get("event_id") == entry.get("event_id"):
                messages.append(build_enriched_message(user_id, open_session, prefix, decision_index, store))
                break

    for message in messages:  # 3. send ...
        await send(user_id, message)

    if closed:  # 4. ... then commit and trim
        _close_sessions(user_id, closed, store)
        buffer.replace(user_id, open_session)
    return messages


def close_idle_user(user_id: str, buffer: BufferIO, store) -> int:
    """Called by the timer once a user has been silent for longer than the
    session gap: every buffered session is complete, so commit and drop
    them. Returns the number of sessions closed."""
    sessions = segment_events_into_sessions(buffer.load(user_id))
    _close_sessions(user_id, sessions, store)
    buffer.replace(user_id, [])
    return len(sessions)


def entry_from_event(event) -> dict:
    """PulseGuardEvent -> buffer entry (plain JSON-able dict)."""
    return {
        "event_id": str(event.event_id),
        "event_type": event.event_type.value,
        "ts": event.ts,
        "decision": event.decision.value if event.decision else None,
        "decision_latency_ms": event.decision_latency_ms,
        "ingest_ts": event.ingest_ts,
        "geo_country": event.geo.country if event.geo else None,
        "device_id": event.device_id,
        "src_ip": event.src_ip,
        "user_agent": event.user_agent,
        "session_id": event.session_id,
    }


def describe_open_session(events: list[dict]) -> Optional[dict]:
    sessions = segment_events_into_sessions(events)
    if not sessions:
        return None
    s = sessions[-1]
    return {
        "n_events": len(s),
        "n_decisions": sum(1 for e in s if e.get("event_type") == "mfa_decision"),
        "started": min(e["ts"] for e in s).isoformat(),
        "last": max(e["ts"] for e in s).isoformat(),
    }
