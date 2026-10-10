"""Live scoring worker (L4): consumes `pulseguard.events.enriched` (one
message per decision point of a session), scores it with the trained Stage
A/B/C models fused at the PERSISTED operating point, records the score,
upserts the session's alert, and publishes to `pulseguard.alerts` for the
mitigation worker.

The running system is the evaluated system (REMEDIATION_TASK.md A2/B2):
  * same unit -- a session-so-far at each decision (feature_table.py);
  * same weights and threshold -- loaded from model_registry/
    operating_point.json, written only by tune_fusion_weights.py on the
    validation split. Missing file or missing model => startup error.
  * same rule -- an alert is raised at the first decision point whose fused
    score crosses the threshold.

Runs as a background thread inside the detection_engine FastAPI app.
Kafka handling (explicit commits, dead-letter path) is in
pulseguard_common.kafka_worker.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import torch
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from pulseguard_common.db.models import Alert, Event, Score
from pulseguard_common.db.session import get_session_factory
from pulseguard_common.kafka_worker import consumer_config, make_dead_letter_sink, run_loop
from pulseguard_common.sessions import session_pairs
from services.detection_engine.app.calibration import calibrate, load_calibrator
from services.detection_engine.app.explain import (
    contributions,
    dominant_stage,
    stage_a_reasons,
    stage_c_reasons,
)
from services.detection_engine.app.explain_shap import make_explainer, top3_reasons
from services.detection_engine.app.feature_table import to_model_matrix
from services.detection_engine.app.fusion import fuse_scores
from services.detection_engine.app.operating_point import OperatingPoint, load_operating_point
from services.detection_engine.app.sequence_dataset import pairs_to_sequence
from services.detection_engine.app.stage_a_statistical import stage_a_score
from services.detection_engine.app.stage_b_xgboost import load_model
from services.detection_engine.app.stage_c_gru import StageCGRU

logger = logging.getLogger("pulseguard.detection_engine.live_scorer")

KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
ENRICHED_TOPIC = "pulseguard.events.enriched"
ALERTS_TOPIC = "pulseguard.alerts"
MODEL_DIR = Path(os.environ.get("MODEL_DIR", "/srv/services/detection_engine/app/model_registry"))

torch.set_num_threads(1)  # one small GRU per message; threads only add contention


class ModelArtifactMissing(RuntimeError):
    pass


def _sequence_events(sequence_raw: list[dict]) -> list[dict]:
    return [
        {
            "event_type": e["event_type"],
            "ts": datetime.fromisoformat(e["ts"]),
            "decision": e.get("decision"),
            "decision_latency_ms": e.get("decision_latency_ms"),
            "ingest_ts": None,
        }
        for e in sequence_raw
    ]


class LiveScorer:
    """Every artifact is required. The old behaviour -- a missing model
    silently scored 0.0 -- produced a running system nothing had evaluated."""

    def __init__(self, model_dir: Path = MODEL_DIR):
        self.operating_point: OperatingPoint = load_operating_point(model_dir / "operating_point.json")
        self.weights = self.operating_point.weights
        self.threshold = self.operating_point.threshold

        for name in ("stage_b.json", "stage_b_calibrator.pkl", "stage_c.pt"):
            if not (model_dir / name).exists():
                raise ModelArtifactMissing(f"{model_dir / name} not found")
        self._stage_b = load_model(model_dir / "stage_b.json")
        self._calibrator = load_calibrator(model_dir / "stage_b_calibrator.pkl")
        self._explainer = make_explainer(self._stage_b)
        self._stage_c = StageCGRU()
        self._stage_c.load_state_dict(torch.load(model_dir / "stage_c.pt", weights_only=True))
        self._stage_c.eval()
        logger.info(
            "Live scorer at operating point weights=(%.2f, %.2f, %.2f) threshold=%.2f",
            self.weights.weight_a, self.weights.weight_b, self.weights.weight_c, self.threshold,
        )

    def score_message(self, message: dict) -> dict:
        vector = message["feature_vector"]
        table = pd.DataFrame([vector])

        stage_a = stage_a_score(vector)
        raw_b = float(self._stage_b.predict_proba(to_model_matrix(table))[:, 1][0])
        stage_b = float(calibrate(self._calibrator, [raw_b])[0])

        seq, length = pairs_to_sequence(session_pairs(_sequence_events(message.get("sequence", []))))
        with torch.no_grad():
            logit = self._stage_c(torch.tensor(seq[None, ...]), torch.tensor([length], dtype=torch.long))
        stage_c = float(torch.sigmoid(logit).item())

        fused = fuse_scores(stage_a, stage_b, stage_c, self.weights)
        return {
            "stage_a_score": stage_a,
            "stage_b_score": stage_b,
            "stage_c_score": stage_c,
            "fused_score": fused,
            "raised": fused >= self.threshold,
            "_seq": (seq, length),
            "_table": table,
        }

    def explain(self, message: dict, scores: dict) -> dict:
        contrib = contributions(scores["stage_a_score"], scores["stage_b_score"], scores["stage_c_score"], self.weights)
        source = dominant_stage(contrib)
        if source == "stage_a":
            reasons = stage_a_reasons(message["feature_vector"])
        elif source == "stage_b":
            reasons = top3_reasons(self._explainer, scores["_table"])
        else:
            seq, length = scores["_seq"]
            reasons = stage_c_reasons(self._stage_c, seq, length)
        return {"source": source, "reasons": reasons, "contributions": contrib}


def _persist_events(db, message: dict, episode: str) -> None:
    rows = [
        {
            "event_id": uuid.UUID(e["event_id"]) if e.get("event_id") else uuid.uuid4(),
            "user_id": message["feature_vector"]["user_id"],
            "ts": datetime.fromisoformat(e["ts"]),
            "event_type": e["event_type"],
            "decision": e.get("decision"),
            "decision_latency_ms": e.get("decision_latency_ms"),
            "src_ip": e.get("src_ip") or "unknown",
            "geo_country": e.get("geo_country"),
            "device_id": e.get("device_id") or "unknown",
            "user_agent": e.get("user_agent") or "unknown",
            "session_id": e.get("session_id") or episode,
            "episode_id": episode,
            "ingest_ts": datetime.fromisoformat(e["ingest_ts"]) if e.get("ingest_ts") else datetime.now(timezone.utc),
        }
        for e in message.get("sequence", [])
    ]
    if rows:
        db.execute(pg_insert(Event).values(rows).on_conflict_do_nothing())


class EnrichedMessageHandler:
    """Idempotent per-message processing: re-delivering a message updates
    the same score row and alert instead of duplicating them."""

    def __init__(self, scorer: LiveScorer, session_factory, producer):
        self.scorer = scorer
        self.session_factory = session_factory
        self.producer = producer

    def __call__(self, raw: bytes) -> None:
        started = time.perf_counter()
        message = json.loads(raw)
        scores = self.scorer.score_message(message)
        scoring_ms = (time.perf_counter() - started) * 1000

        vector = message["feature_vector"]
        user_id = vector["user_id"]
        episode = message.get("episode_id") or message.get("session_id") or str(uuid.uuid4())
        decision_index = int(message.get("decision_index", 0))
        trigger = (message.get("sequence") or [{}])[-1]
        now = datetime.now(timezone.utc)

        publish = None
        db = self.session_factory()
        try:
            _persist_events(db, message, episode)
            score_row = dict(
                ts=datetime.fromisoformat(trigger["ts"]) if trigger.get("ts") else now,
                user_id=user_id, episode_id=episode, decision_index=decision_index,
                decision=trigger.get("decision"), decision_latency_ms=trigger.get("decision_latency_ms"),
                stage_a_score=scores["stage_a_score"], stage_b_score=scores["stage_b_score"],
                stage_c_score=scores["stage_c_score"], fused_score=scores["fused_score"],
                threshold=self.scorer.threshold, raised=scores["raised"], scoring_ms=scoring_ms,
            )
            db.execute(pg_insert(Score).values(**score_row).on_conflict_do_nothing())

            alert = db.scalars(select(Alert).where(Alert.burst_id == episode)).first()
            if alert is None and scores["raised"]:
                explanation = self.scorer.explain(message, scores)
                alert = Alert(
                    alert_id=uuid.uuid4(), user_id=user_id, ts=now, updated_ts=now,
                    stage_a_score=scores["stage_a_score"], stage_b_score=scores["stage_b_score"],
                    stage_c_score=scores["stage_c_score"], fused_score=scores["fused_score"],
                    calibrated_probability=scores["stage_b_score"], shap_top3=explanation["reasons"],
                    explanation_source=explanation["source"], feature_vector=vector, burst_id=episode,
                    n_decisions=decision_index + 1, first_crossing_decision=decision_index, status="open",
                )
                db.add(alert)
                publish = "raised"
            elif alert is not None:
                alert.n_decisions = max(alert.n_decisions or 0, decision_index + 1)
                alert.updated_ts = now
                if scores["fused_score"] > alert.fused_score:
                    explanation = self.scorer.explain(message, scores)
                    alert.stage_a_score = scores["stage_a_score"]
                    alert.stage_b_score = scores["stage_b_score"]
                    alert.stage_c_score = scores["stage_c_score"]
                    alert.fused_score = scores["fused_score"]
                    alert.calibrated_probability = scores["stage_b_score"]
                    alert.shap_top3 = explanation["reasons"]
                    alert.explanation_source = explanation["source"]
                    alert.feature_vector = vector
                # An approval inside an already-alerted session is the moment
                # in-band mitigation exists for: ask the controller again.
                if trigger.get("decision") == "approve":
                    publish = "approval_in_alerted_session"
            db.commit()
            alert_id = str(alert.alert_id) if alert is not None else None
            fused_for_alert = alert.fused_score if alert is not None else scores["fused_score"]
        finally:
            db.close()

        if publish and alert_id:
            self.producer.produce(
                ALERTS_TOPIC,
                key=user_id.encode("utf-8"),
                value=json.dumps({
                    "alert_id": alert_id, "user_id": user_id, "fused_score": fused_for_alert,
                    "burst_id": episode, "episode_id": episode, "reason": publish,
                    "decision": trigger.get("decision"), "ts": now.isoformat(),
                }).encode("utf-8"),
            )
            self.producer.flush(5.0)
        logger.info(
            "Scored user=%s episode=%s decision=%d fused=%.3f raised=%s (%.1f ms)",
            user_id, episode, decision_index, scores["fused_score"], scores["raised"], scoring_ms,
        )


def run_live_scorer_loop(stop_event: threading.Event, scorer: LiveScorer) -> None:
    from confluent_kafka import Consumer, Producer

    session_factory = get_session_factory()
    producer = Producer({"bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS})
    consumer = Consumer(consumer_config(KAFKA_BOOTSTRAP_SERVERS, "detection-engine-v2"))
    handler = EnrichedMessageHandler(scorer, session_factory, producer)
    sink = make_dead_letter_sink("detection_engine", producer, session_factory)
    logger.info("Live scorer consuming %s", ENRICHED_TOPIC)
    run_loop(consumer, [ENRICHED_TOPIC], handler, sink, stop_event)
