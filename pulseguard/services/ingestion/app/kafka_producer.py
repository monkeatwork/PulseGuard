"""Kafka producer for canonical PulseGuardEvents (L2 ingestion).

Serializes each event to the canonical JSON schema (pulseguard_common.event_schema)
and produces it to `pulseguard.events.raw`, partitioned by user_id so a
single user's events are always processed in order by the same
feature-engine partition.
"""

from __future__ import annotations

import os

from confluent_kafka import Producer

from pulseguard_common.event_schema import PulseGuardEvent

RAW_EVENTS_TOPIC = "pulseguard.events.raw"


class EventProducer:
    def __init__(self, bootstrap_servers: str | None = None):
        servers = bootstrap_servers or os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
        self._producer = Producer({"bootstrap.servers": servers})

    def produce(self, event: PulseGuardEvent) -> None:
        payload = event.model_dump_json().encode("utf-8")
        self._producer.produce(
            RAW_EVENTS_TOPIC,
            key=event.user_id.encode("utf-8"),
            value=payload,
        )
        # Non-blocking local queue poll so delivery callbacks/errors surface
        # without stalling the producer loop.
        self._producer.poll(0)

    def flush(self, timeout: float = 10.0) -> int:
        return self._producer.flush(timeout)
