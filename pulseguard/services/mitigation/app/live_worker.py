"""Live mitigation worker (L5): consumes `pulseguard.alerts`, applies the
real cooldown/escalation controller per user, writes real
mitigation_actions rows, and calls the real webhook client.

Runs as a background thread inside the mitigation FastAPI app's lifespan
(confluent-kafka's Consumer — same pattern as detection_engine's
live_scorer.py, no Faust needed for a straight consume-decide-write loop).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone

from confluent_kafka import Consumer

from pulseguard_common.db.models import MitigationAction
from pulseguard_common.db.session import get_session_factory
from services.mitigation.app.controller import UserMitigationState, decide_action
from services.mitigation.app.webhook_client import StepUpWebhookClient

logger = logging.getLogger("pulseguard.mitigation.live_worker")

KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "redpanda:9092")
ALERTS_TOPIC = "pulseguard.alerts"
# Any alert whose fused score meets or exceeds this is worth a mitigation
# decision at all (below this, cooldown/escalation state isn't touched).
# Deliberately lower than a "confirmed attack" threshold -- the controller
# itself is what decides whether to actually act (cooldown/escalation),
# this just gates whether an alert is worth considering.
MITIGATION_CONSIDERATION_THRESHOLD = float(os.environ.get("MITIGATION_CONSIDERATION_THRESHOLD", "0.3"))
IDP_WEBHOOK_URL = os.environ.get("IDP_WEBHOOK_URL", "http://keycloak:8080")


def run_live_mitigation_loop(stop_event: threading.Event) -> None:
    consumer = Consumer(
        {
            "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
            "group.id": "mitigation-v1",
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe([ALERTS_TOPIC])
    session_factory = get_session_factory()
    webhook_client = StepUpWebhookClient(IDP_WEBHOOK_URL)
    user_states: dict[str, UserMitigationState] = {}

    logger.info("Live mitigation worker started, consuming %s", ALERTS_TOPIC)
    try:
        while not stop_event.is_set():
            msg = consumer.poll(1.0)
            if msg is None or msg.error():
                continue
            try:
                alert = json.loads(msg.value())
                user_id = alert["user_id"]
                fused_score = alert["fused_score"]
                if fused_score < MITIGATION_CONSIDERATION_THRESHOLD:
                    continue

                state = user_states.setdefault(user_id, UserMitigationState())
                now = datetime.now(timezone.utc)
                action = decide_action(state, now)

                if action == "step_up_required":
                    success = webhook_client.trigger_step_up(
                        user_id, alert.get("burst_id") or "", f"fused_score={fused_score:.3f}"
                    )
                    if not success:
                        state.record_failure(now)
                elif action == "alt_factor_required":
                    webhook_client.trigger_alt_factor(
                        user_id, alert.get("burst_id") or "", "escalated after repeated step-up failures"
                    )

                db = session_factory()
                try:
                    db.add(
                        MitigationAction(
                            action_id=uuid.uuid4(),
                            user_id=user_id,
                            ts=now,
                            action_type=action,
                            consecutive_failures=len(state.failure_timestamps),
                        )
                    )
                    db.commit()
                    logger.info(
                        "Mitigation action=%s for user=%s (fused_score=%.3f)", action, user_id, fused_score
                    )
                finally:
                    db.close()
            except Exception:
                logger.exception("Failed to process alert message")
    finally:
        consumer.close()
