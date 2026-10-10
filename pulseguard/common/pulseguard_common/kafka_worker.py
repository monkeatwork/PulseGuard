"""At-least-once Kafka consumption with a dead-letter path, shared by the
detection engine's live scorer and the mitigation worker
(REMEDIATION_TASK.md C1).

Before this, both workers used confluent-kafka's default auto-commit and
caught every exception with a log line: a crash mid-batch silently dropped
or double-processed messages, and a systematically malformed message was
lost forever. Now, per message:

  * success            -> commit THIS message's offset (synchronously);
  * handler raised     -> the message goes to the dead-letter sink (Kafka
                          topic `pulseguard.dlq` + the `dead_letters` table),
                          and only once that write succeeded is the offset
                          committed;
  * dead-letter failed -> NOT committed; the consumer seeks back to the
                          message so it is retried. Offsets never advance
                          past a message that was neither processed nor
                          preserved.

Auto-commit is disabled, so a crash before any of these commits replays the
message on restart (handlers are written to be idempotent: alerts are
upserted by episode id, events insert ON CONFLICT DO NOTHING).
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Protocol

logger = logging.getLogger("pulseguard.kafka_worker")

DLQ_TOPIC = "pulseguard.dlq"

OK = "ok"
DEAD_LETTERED = "dead_lettered"
RETRY = "retry"


class DeadLetterSink(Protocol):
    def __call__(self, msg, error: BaseException) -> None: ...


def consumer_config(bootstrap: str, group_id: str) -> dict:
    return {
        "bootstrap.servers": bootstrap,
        "group.id": group_id,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    }


def handle_message(msg, handler: Callable[[bytes], None], dead_letter: DeadLetterSink, consumer) -> str:
    try:
        handler(msg.value())
    except Exception as exc:  # noqa: BLE001 -- every failure must be preserved, not swallowed
        logger.exception("Handler failed for %s[%s]@%s", msg.topic(), msg.partition(), msg.offset())
        try:
            dead_letter(msg, exc)
        except Exception:  # noqa: BLE001
            logger.exception("Dead-letter write failed; will retry offset %s", msg.offset())
            from confluent_kafka import TopicPartition

            consumer.seek(TopicPartition(msg.topic(), msg.partition(), msg.offset()))
            return RETRY
        consumer.commit(message=msg, asynchronous=False)
        return DEAD_LETTERED
    consumer.commit(message=msg, asynchronous=False)
    return OK


def make_dead_letter_sink(source: str, producer, session_factory) -> DeadLetterSink:
    """Writes to the `pulseguard.dlq` topic AND the `dead_letters` table (so
    the dashboard can show them). Raises if either write fails, which makes
    handle_message retry rather than commit."""
    from datetime import datetime, timezone

    from pulseguard_common.db.models import DeadLetter

    def sink(msg, error: BaseException) -> None:
        payload = msg.value()
        text = payload.decode("utf-8", errors="replace") if isinstance(payload, (bytes, bytearray)) else str(payload)
        producer.produce(
            DLQ_TOPIC,
            value=payload,
            headers={"source": source, "error": repr(error)[:500], "origin_topic": msg.topic()},
        )
        if producer.flush(10.0) != 0:
            raise RuntimeError("DLQ produce not acknowledged")
        db = session_factory()
        try:
            db.add(DeadLetter(ts=datetime.now(timezone.utc), source=source, topic=msg.topic(),
                              kafka_partition=msg.partition(), kafka_offset=msg.offset(),
                              error=repr(error)[:2000], payload=text[:20000]))
            db.commit()
        finally:
            db.close()

    return sink


def run_loop(consumer, topics: list[str], handler, dead_letter: DeadLetterSink, stop_event: threading.Event) -> None:
    consumer.subscribe(topics)
    try:
        while not stop_event.is_set():
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                logger.warning("Kafka error: %s", msg.error())
                continue
            handle_message(msg, handler, dead_letter, consumer)
    finally:
        consumer.close()
