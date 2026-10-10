"""Benchmark-corpus replay adapter (L1): replays real labelled episodes from
the benchmark corpus (RBA benign base + the seeded attack generators)
through the real ingestion -> Kafka -> feature engine -> detection ->
mitigation pipeline.

Two time modes:

* ``preserve`` (default): every event keeps its ORIGINAL spacing from the
  corpus, anchored so the episode ends at the moment the replay started, and
  events are published `pace_seconds` apart. A low-and-slow episode spread
  over five hours therefore replays in seconds with exactly the timestamps,
  gaps and latencies the offline evaluation scored -- so the live features
  are the evaluated features. `ingest_ts` follows the corpus (the generator
  records ingest_ts = ts); it is a recorded episode, not live traffic.
* ``realtime``: timestamps are anchored at "now" and gaps divided by
  `speedup`, with true wall-clock pacing and true receipt times. Note that
  compressing gaps changes the frequency features (and with them the
  scores): a 30-minute low-and-slow gap replayed at 60x is a 30-second gap.

Each replay runs as a fresh user id (`<corpus user>#<run>`) so two replays of
the same episode never merge into one session.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Iterator, Literal

import pandas as pd

from pulseguard_common.event_schema import Decision, EventType, Geo, PulseGuardEvent
from services.ingestion.app.adapters.base import TelemetryAdapter

logger = logging.getLogger("pulseguard.ingestion.replay")

TimeMode = Literal["preserve", "realtime"]


def _row_to_event(row: dict, user_id: str, ts: datetime, ingest_ts: datetime) -> PulseGuardEvent:
    decision = Decision(row["decision"]) if pd.notna(row.get("decision")) else None
    latency = int(row["decision_latency_ms"]) if pd.notna(row.get("decision_latency_ms")) else None
    geo = Geo(country=row["geo_country"]) if pd.notna(row.get("geo_country")) else None
    return PulseGuardEvent(
        event_id=uuid.uuid4(),
        user_id=user_id,
        ts=ts,
        event_type=EventType(row["event_type"]),
        decision=decision,
        decision_latency_ms=latency,
        src_ip=row["src_ip"],
        geo=geo,
        device_id=row["device_id"],
        user_agent=row["user_agent"],
        session_id=str(row["session_id"]),
        ingest_ts=ingest_ts,
    )


def load_episode(events_parquet_path: str, burst_id: str) -> pd.DataFrame:
    df = pd.read_parquet(events_parquet_path, filters=[("burst_id", "==", burst_id)])
    episode = df[df["burst_id"] == burst_id].sort_values("ts")
    if episode.empty:
        raise ValueError(f"burst_id {burst_id} not found in {events_parquet_path}")
    return episode


class ReplayAdapter(TelemetryAdapter):
    name = "replay"

    def __init__(
        self,
        episode: pd.DataFrame,
        user_id: str,
        time_mode: TimeMode = "preserve",
        pace_seconds: float = 0.5,
        speedup: float = 1.0,
        sleep=time.sleep,
    ):
        if time_mode not in ("preserve", "realtime"):
            raise ValueError("time_mode must be 'preserve' or 'realtime'")
        if speedup <= 0:
            raise ValueError("speedup must be positive")
        self.episode = episode.sort_values("ts")
        self.user_id = user_id
        self.time_mode = time_mode
        self.pace_seconds = max(0.0, pace_seconds)
        self.speedup = speedup
        self._sleep = sleep

    def events(self) -> Iterator[PulseGuardEvent]:
        rows = self.episode.to_dict("records")
        first_ts = rows[0]["ts"].to_pydatetime()
        last_ts = rows[-1]["ts"].to_pydatetime()
        anchor = datetime.now(timezone.utc)
        prev_ts = None
        for i, row in enumerate(rows):
            original = row["ts"].to_pydatetime()
            if self.time_mode == "preserve":
                ts = anchor - (last_ts - original)
                event = _row_to_event(row, self.user_id, ts, ingest_ts=ts)
                if i > 0 and self.pace_seconds:
                    self._sleep(self.pace_seconds)
            else:
                ts = anchor + (original - first_ts) / self.speedup
                if prev_ts is not None:
                    gap = (ts - prev_ts).total_seconds()
                    if gap > 0:
                        self._sleep(gap)
                event = _row_to_event(row, self.user_id, ts, ingest_ts=datetime.now(timezone.utc))
            prev_ts = ts
            yield event


def list_replayable_bursts(events_parquet_path: str, profile: str | None = None, limit: int = 20) -> list[dict]:
    df = pd.read_parquet(
        events_parquet_path,
        columns=["burst_id", "user_id", "attack_profile", "label_attack", "ts", "event_type", "decision"],
    )
    labelled = df[df["burst_id"].notna()].copy()
    labelled["attack_profile"] = labelled["attack_profile"].where(labelled["attack_profile"].notna(), None)
    if profile:
        if profile in ("benign_high_activity", "benign_occasional_denial"):
            labelled = labelled[labelled["burst_id"].str.contains(f":{profile}:", regex=False)]
        else:
            labelled = labelled[labelled["attack_profile"] == profile]
    labelled["is_prompt"] = labelled["event_type"] == "mfa_prompt"
    labelled["is_deny"] = labelled["decision"] == "deny"
    summary = (
        labelled.groupby("burst_id")
        .agg(
            user_id=("user_id", "first"),
            attack_profile=("attack_profile", "first"),
            label_attack=("label_attack", "first"),
            n_events=("ts", "count"),
            n_prompts=("is_prompt", "sum"),
            n_denials=("is_deny", "sum"),
            start=("ts", "min"),
            end=("ts", "max"),
        )
        .reset_index()
    )
    summary["profile"] = summary["burst_id"].str.split(":").str[-2]
    summary["duration_seconds"] = (summary["end"] - summary["start"]).dt.total_seconds()
    summary = summary.drop(columns=["start", "end"]).head(limit)
    return [
        {k: (v.item() if hasattr(v, "item") else v) for k, v in record.items()}
        for record in summary.to_dict("records")
    ]
