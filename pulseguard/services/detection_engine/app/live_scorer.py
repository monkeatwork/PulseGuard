"""Live scoring worker (L4): consumes `pulseguard.events.enriched`, scores
each burst via the real trained Stage A/B/C models + fusion, writes a real
Alert row to Postgres, and republishes the fused decision to
`pulseguard.alerts` for the mitigation worker to act on.

Runs as a background thread inside the detection_engine FastAPI app's
lifespan (confluent-kafka's Consumer, not Faust — a straight
consume-score-write loop doesn't need Faust's stateful table/timer
machinery, which feature_engine's burst-buffering does).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import torch
from confluent_kafka import Consumer, Producer

from pulseguard_common.db.models import Alert, Event
from pulseguard_common.db.session import get_session_factory
from services.detection_engine.app.calibration import calibrate, load_calibrator
from services.detection_engine.app.explain_shap import make_explainer, top3_reasons
from services.detection_engine.app.feature_table import to_model_matrix
from services.detection_engine.app.fusion import FusionWeights, fuse_scores
from services.detection_engine.app.sequence_dataset import pairs_to_sequence
from services.detection_engine.app.stage_a_statistical import stage_a_score
from services.detection_engine.app.stage_b_xgboost import load_model
from services.detection_engine.app.stage_c_gru import StageCGRU
from pulseguard_common.windows import pair_prompts_and_decisions

logger = logging.getLogger("pulseguard.detection_engine.live_scorer")

KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "redpanda:9092")
ENRICHED_TOPIC = "pulseguard.events.enriched"
ALERTS_TOPIC = "pulseguard.alerts"
STAGE_B_MODEL_PATH = Path(
    os.environ.get("STAGE_B_MODEL_PATH", "/srv/services/detection_engine/app/model_registry/stage_b.json")
)
STAGE_C_MODEL_PATH = Path(
    os.environ.get("STAGE_C_MODEL_PATH", "/srv/services/detection_engine/app/model_registry/stage_c.pt")
)

# The score at or above which a burst is actually RAISED as an alert. This
# is not a new number: it is the frozen full-fusion operating point from
# `eval/results/full_fusion.json`, tuned on the validation split in Phase 5
# and the same threshold every reported precision/recall/FPR figure was
# measured at. Inventing a different one here would mean the live system
# operated at a point nothing was ever evaluated at.
#
# Every scored burst is still persisted to `events` regardless -- that is
# telemetry and belongs in the hypertable either way. Only the `alerts`
# row is gated, because `alerts` is the SOC analyst's work queue: writing
# a row for every benign burst that scored ~0.001 turns the dashboard into
# a log tail and buries the real detections, which is the opposite of what
# L5 is for.
ALERT_THRESHOLD = float(os.environ.get("ALERT_THRESHOLD", "0.01"))


def _sequence_to_pairs(sequence_raw: list[dict]):
    events = [
        {
            "event_type": e["event_type"],
            "ts": datetime.fromisoformat(e["ts"]),
            "decision": e.get("decision"),
            "decision_latency_ms": e.get("decision_latency_ms"),
            "ingest_ts": None,
        }
        for e in sequence_raw
    ]
    return pair_prompts_and_decisions(events)


class LiveScorer:
    """Loads whatever trained model artifacts are present at startup. A
    missing artifact degrades that stage's contribution to 0.0 rather than
    crashing -- the live pipeline should come up even before models have
    been trained (e.g. right after `docker compose up` on a fresh clone,
    before `train_stage_b.py`/`train_stage_c.py` have ever been run)."""

    def __init__(self):
        self._stage_b_model = None
        self._calibrator = None
        self._explainer = None
        self._stage_c_model = None
        self._weights = FusionWeights()
        self._load_models()

    def _load_models(self) -> None:
        if STAGE_B_MODEL_PATH.exists():
            self._stage_b_model = load_model(STAGE_B_MODEL_PATH)
            self._explainer = make_explainer(self._stage_b_model)
            calibrator_path = STAGE_B_MODEL_PATH.parent / "stage_b_calibrator.pkl"
            if calibrator_path.exists():
                self._calibrator = load_calibrator(calibrator_path)
            logger.info("Loaded Stage B model + calibrator from %s", STAGE_B_MODEL_PATH)
        else:
            logger.warning("Stage B model not found at %s -- stage_b_score will be 0.0", STAGE_B_MODEL_PATH)

        if STAGE_C_MODEL_PATH.exists():
            model = StageCGRU()
            model.load_state_dict(torch.load(STAGE_C_MODEL_PATH))
            model.eval()
            self._stage_c_model = model
            logger.info("Loaded Stage C model from %s", STAGE_C_MODEL_PATH)
        else:
            logger.warning("Stage C model not found at %s -- stage_c_score will be 0.0", STAGE_C_MODEL_PATH)

    def score_message(self, message: dict) -> dict:
        feature_vector = message["feature_vector"]
        sequence_raw = message.get("sequence", [])

        stage_a = stage_a_score(feature_vector)

        stage_b = 0.0
        shap_top3 = None
        if self._stage_b_model is not None:
            table = pd.DataFrame([feature_vector])
            matrix = to_model_matrix(table)
            raw_b = float(self._stage_b_model.predict_proba(matrix)[:, 1][0])
            stage_b = float(calibrate(self._calibrator, [raw_b])[0]) if self._calibrator is not None else raw_b
            if self._explainer is not None:
                shap_top3 = top3_reasons(self._explainer, table)

        stage_c = 0.0
        if self._stage_c_model is not None and sequence_raw:
            pairs = _sequence_to_pairs(sequence_raw)
            seq, length = pairs_to_sequence(pairs)
            with torch.no_grad():
                logit = self._stage_c_model(
                    torch.tensor(seq[None, ...], dtype=torch.float32),
                    torch.tensor([length], dtype=torch.long),
                )
            stage_c = float(torch.sigmoid(logit).item())

        fused = fuse_scores(stage_a, stage_b, stage_c, self._weights)

        return {
            "stage_a_score": stage_a,
            "stage_b_score": stage_b,
            "stage_c_score": stage_c,
            "fused_score": fused,
            "shap_top3": shap_top3,
        }


def run_live_scorer_loop(stop_event: threading.Event) -> None:
    scorer = LiveScorer()
    consumer = Consumer(
        {
            "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
            "group.id": "detection-engine-v1",
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe([ENRICHED_TOPIC])
    producer = Producer({"bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS})
    session_factory = get_session_factory()

    logger.info("Live scorer started, consuming %s", ENRICHED_TOPIC)
    try:
        while not stop_event.is_set():
            msg = consumer.poll(1.0)
            if msg is None or msg.error():
                continue
            try:
                message = json.loads(msg.value())
                scores = scorer.score_message(message)
                user_id = message["feature_vector"]["user_id"]
                now = datetime.now(timezone.utc)
                alert_id = uuid.uuid4()

                session_id = message.get("session_id")
                raised = scores["fused_score"] >= ALERT_THRESHOLD
                db = session_factory()
                try:
                    if raised:
                        db.add(
                            Alert(
                                alert_id=alert_id,
                                user_id=user_id,
                                ts=now,
                                stage_a_score=scores["stage_a_score"],
                                stage_b_score=scores["stage_b_score"],
                                stage_c_score=scores["stage_c_score"],
                                fused_score=scores["fused_score"],
                                calibrated_probability=scores["fused_score"],
                                shap_top3=scores["shap_top3"],
                                burst_id=session_id,
                            )
                        )
                    # The dashboard's GET /alerts/{id} reconstructs the
                    # latency-trajectory chart by querying `events` for
                    # this session_id -- write the real sequence here so
                    # that lookup finds real rows, not just the aggregate
                    # feature vector.
                    for raw_event in message.get("sequence", []):
                        db.add(
                            Event(
                                event_id=uuid.uuid4(),
                                user_id=user_id,
                                ts=datetime.fromisoformat(raw_event["ts"]),
                                event_type=raw_event["event_type"],
                                decision=raw_event.get("decision"),
                                decision_latency_ms=raw_event.get("decision_latency_ms"),
                                src_ip="0.0.0.0",
                                device_id="unknown",
                                user_agent="unknown",
                                session_id=session_id or str(alert_id),
                                ingest_ts=now,
                            )
                        )
                    db.commit()
                finally:
                    db.close()

                if raised:
                    producer.produce(
                        ALERTS_TOPIC,
                        key=user_id.encode("utf-8"),
                        value=json.dumps(
                            {
                                "alert_id": str(alert_id),
                                "user_id": user_id,
                                "fused_score": scores["fused_score"],
                                "burst_id": message.get("session_id"),
                                "ts": now.isoformat(),
                            }
                        ).encode("utf-8"),
                    )
                    producer.poll(0)
                logger.info(
                    "Scored user=%s fused_score=%.3f raised=%s",
                    user_id,
                    scores["fused_score"],
                    raised,
                )
            except Exception:
                logger.exception("Failed to process enriched message")
    finally:
        consumer.close()
        producer.flush(5.0)
