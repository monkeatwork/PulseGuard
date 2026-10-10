"""Benchmark-corpus replay adapter (L1): the only genuinely real event
source available without a live IdP in this environment. Replays actual
labelled episodes from the already-validated benchmark corpus
(data/generated_full/events.parquet — real Zenodo RBA data plus the
tested attack-profile generators) through the real ingestion -> Kafka ->
Faust -> detection -> mitigation pipeline.

Timestamps are remapped to start "now" (preserving each episode's real
relative gaps, optionally divided by `speedup`) rather than replayed at
their original historical values -- this matters mechanically, not just
cosmetically: the feature engine's grace-window finalization
(`windows.is_burst_finalizable`) compares real wall-clock time against the
event's own `ts`, so historical timestamps would cause every burst to
finalize instantly regardless of whether more events are still arriving.

`speedup` > 1.0 compresses gaps. Be aware: compressing `low_and_slow`'s
20-40 minute gaps below `BURST_GAP_THRESHOLD_SECONDS` (5 min) would merge
fragments that are supposed to stay separate, changing the qualitative
behaviour the whole project is built around — see DECISIONS.md. Default
speedup=1.0 (no distortion) for that reason; `high_volume_burst` and
`social_engineering_assisted` complete in minutes at real speed anyway.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone

import pandas as pd

from pulseguard_common.event_schema import Decision, EventType, Geo, PulseGuardEvent
from services.ingestion.app.kafka_producer import EventProducer

logger = logging.getLogger("pulseguard.ingestion.replay")


def _row_to_event(row: pd.Series, new_ts: datetime) -> PulseGuardEvent:
    decision = Decision(row["decision"]) if pd.notna(row["decision"]) else None
    latency = int(row["decision_latency_ms"]) if pd.notna(row["decision_latency_ms"]) else None
    geo = Geo(country=row["geo_country"]) if pd.notna(row["geo_country"]) else None
    return PulseGuardEvent(
        event_id=uuid.uuid4(),
        user_id=str(row["user_id"]),
        ts=new_ts,
        event_type=EventType(row["event_type"]),
        decision=decision,
        decision_latency_ms=latency,
        src_ip=row["src_ip"],
        geo=geo,
        device_id=row["device_id"],
        user_agent=row["user_agent"],
        session_id=str(row["session_id"]),
        ingest_ts=datetime.now(timezone.utc),  # true collector-receipt time
    )


def replay_burst(
    events_parquet_path: str,
    burst_id: str,
    producer: EventProducer,
    speedup: float = 1.0,
) -> int:
    """Replays one burst_id's events anchored to start "now", with each
    event's gap from the episode start divided by `speedup`. Returns the
    number of events produced. Blocks for the (speedup-divided) duration of
    the episode -- callers running this from an HTTP handler should run it
    in a background thread/task.

    `speedup` must compress the event TIMESTAMPS, not just the wall-clock
    sleep between publishes. Getting this wrong is subtle and was a real
    bug: if the emitted `ts` keeps its original spacing while publishing is
    compressed, every event after the first carries a timestamp in the
    FUTURE, and the feature engine's grace-window finalization
    (`now > last_prompt_ts + grace`) then waits for wall-clock time to
    catch up to those future timestamps -- so bursts silently never
    finalize and no alert is ever produced.
    """
    df = pd.read_parquet(events_parquet_path)
    burst = df[df["burst_id"] == burst_id].sort_values("ts")
    if burst.empty:
        raise ValueError(f"burst_id {burst_id} not found in {events_parquet_path}")

    first_ts = burst.iloc[0]["ts"].to_pydatetime()
    now = datetime.now(timezone.utc)

    count = 0
    prev_ts = None
    for _, row in burst.iterrows():
        original_ts = row["ts"].to_pydatetime()
        # Compress the offset from episode start, so emitted timestamps
        # track wall-clock time as the replay proceeds.
        compressed_offset = (original_ts - first_ts) / speedup
        new_ts = now + compressed_offset
        event = _row_to_event(row, new_ts)

        if prev_ts is not None:
            gap = (event.ts - prev_ts).total_seconds()
            if gap > 0:
                logger.info("Sleeping %.1fs before next event (speedup %.1fx)", gap, speedup)
                time.sleep(gap)
        producer.produce(event)
        count += 1
        prev_ts = event.ts

    producer.flush()
    logger.info("Replayed %d events for burst_id=%s", count, burst_id)
    return count


def list_replayable_bursts(
    events_parquet_path: str, profile: str | None = None, limit: int = 20
) -> list[dict]:
    df = pd.read_parquet(events_parquet_path)
    labelled = df[df["burst_id"].notna()]
    if profile:
        labelled = labelled[labelled["attack_profile"] == profile]
    summary = (
        labelled.groupby("burst_id")
        .agg(
            user_id=("user_id", "first"),
            attack_profile=("attack_profile", "first"),
            label_attack=("label_attack", "first"),
            n_events=("ts", "count"),
        )
        .reset_index()
    )
    return summary.head(limit).to_dict("records")
