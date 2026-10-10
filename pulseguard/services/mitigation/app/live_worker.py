"""Live mitigation worker (L5): consumes `pulseguard.alerts`, applies the
cooldown/escalation controller per user, records each action (linked to its
alert), and calls the IdP's step-up / alternate-factor webhook.

The outcome of a step-up challenge arrives later from the IdP
(POST /feedback on this service, see main.py) and is what drives escalation:
3 failed step-ups within 30 minutes escalate to an alternate factor -- never
to a lockout (controller.py's anti-DoS invariant).

Kafka handling (explicit commits, dead-letter path) is in
pulseguard_common.kafka_worker (REMEDIATION_TASK.md C1).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone

from pulseguard_common.db.models import MitigationAction
from pulseguard_common.db.session import get_session_factory
from pulseguard_common.kafka_worker import consumer_config, make_dead_letter_sink, run_loop
from services.mitigation.app.controller import UserMitigationState, decide_action
from services.mitigation.app.webhook_client import StepUpWebhookClient

logger = logging.getLogger("pulseguard.mitigation.live_worker")

KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
ALERTS_TOPIC = "pulseguard.alerts"
# Second, independent gate: an alert must also clear this before the
# controller is consulted. Alerts are already gated at the evaluated
# operating point by the detection engine; this guards the mitigation path
# on its own (defence in depth, DECISIONS.md 2026-09-21).
MITIGATION_CONSIDERATION_THRESHOLD = float(os.environ.get("MITIGATION_CONSIDERATION_THRESHOLD", "0.3"))
IDP_WEBHOOK_URL = os.environ.get("IDP_WEBHOOK_URL", "http://ingestion:8001/idp")


class UserStates:
    """Per-user controller state, shared between the Kafka worker thread and
    the /feedback HTTP handler."""

    def __init__(self):
        self._lock = threading.Lock()
        self._states: dict[str, UserMitigationState] = {}

    def get(self, user_id: str) -> UserMitigationState:
        with self._lock:
            return self._states.setdefault(user_id, UserMitigationState())

    def snapshot(self, user_id: str) -> dict:
        state = self.get(user_id)
        return {
            "last_step_up_ts": state.last_step_up_ts.isoformat() if state.last_step_up_ts else None,
            "recent_failures": [ts.isoformat() for ts in state.failure_timestamps],
        }


USER_STATES = UserStates()


class AlertHandler:
    def __init__(self, session_factory, webhook: StepUpWebhookClient, states: UserStates = USER_STATES):
        self.session_factory = session_factory
        self.webhook = webhook
        self.states = states

    def __call__(self, raw: bytes) -> str | None:
        alert = json.loads(raw)
        user_id = alert["user_id"]
        fused_score = float(alert["fused_score"])
        if fused_score < MITIGATION_CONSIDERATION_THRESHOLD:
            return None

        state = self.states.get(user_id)
        now = datetime.now(timezone.utc)
        action = decide_action(state, now)
        episode = alert.get("episode_id") or alert.get("burst_id") or ""

        if action == "step_up_required":
            if not self.webhook.trigger_step_up(user_id, episode, f"fused_score={fused_score:.3f}"):
                # the challenge could not even be issued: count it as unconfirmed
                state.record_failure(now)
        elif action == "alt_factor_required":
            self.webhook.trigger_alt_factor(user_id, episode, "escalated after repeated step-up failures")

        db = self.session_factory()
        try:
            db.add(
                MitigationAction(
                    action_id=uuid.uuid4(),
                    user_id=user_id,
                    ts=now,
                    action_type=action,
                    alert_id=uuid.UUID(alert["alert_id"]) if alert.get("alert_id") else None,
                    consecutive_failures=len(state.failure_timestamps),
                )
            )
            db.commit()
        finally:
            db.close()
        logger.info("Mitigation action=%s user=%s fused=%.3f", action, user_id, fused_score)
        return action


def run_live_mitigation_loop(stop_event: threading.Event) -> None:
    from confluent_kafka import Consumer, Producer

    session_factory = get_session_factory()
    handler = AlertHandler(session_factory, StepUpWebhookClient(IDP_WEBHOOK_URL))
    producer = Producer({"bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS})
    consumer = Consumer(consumer_config(KAFKA_BOOTSTRAP_SERVERS, "mitigation-v2"))
    sink = make_dead_letter_sink("mitigation", producer, session_factory)
    logger.info("Live mitigation worker consuming %s", ALERTS_TOPIC)
    run_loop(consumer, [ALERTS_TOPIC], handler, sink, stop_event)
