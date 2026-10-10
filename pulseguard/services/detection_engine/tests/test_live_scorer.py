"""The live scorer runs at the persisted operating point and refuses to run
without it (REMEDIATION_TASK.md B2); its message handler upserts one alert
per session and is idempotent under redelivery."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
import pytest
import torch
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from testcontainers.community.postgres import PostgresContainer

from services.detection_engine.app.calibration import fit_calibrator, save_calibrator
from services.detection_engine.app.feature_table import FEATURE_COLUMNS
from services.detection_engine.app.live_scorer import EnrichedMessageHandler, LiveScorer, ModelArtifactMissing
from services.detection_engine.app.operating_point import (
    OperatingPoint,
    OperatingPointMissing,
    load_operating_point,
    save_operating_point,
)
from services.detection_engine.app.stage_b_xgboost import save_model, train_stage_b
from services.detection_engine.app.stage_c_gru import StageCGRU
from services.detection_engine.app.stage_c_numpy import export_state_dict

REPO_ROOT = Path(__file__).resolve().parents[3]
INIT_SQL_PATH = REPO_ROOT / "infra" / "postgres" / "init.sql"
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)

POINT = OperatingPoint(
    weight_a=0.15, weight_b=0.35, weight_c=0.5, threshold=0.37, stage_b_threshold=0.4, stage_c_threshold=0.6,
    seed=42, events_sha256="x", tuned_on="val", unit="episode", created_at="2026-10-11T00:00:00+00:00",
)


@pytest.fixture(scope="module")
def model_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("model_registry")
    rng = np.random.default_rng(0)
    X = pd.DataFrame(rng.random((200, len(FEATURE_COLUMNS))), columns=FEATURE_COLUMNS)
    y = pd.Series(rng.random(200) > 0.5)
    model = train_stage_b(X[:150], y[:150], X[150:], y[150:])
    save_model(model, d / "stage_b.json")
    save_calibrator(fit_calibrator(model.predict_proba(X[150:])[:, 1], y[150:].to_numpy()), d / "stage_b_calibrator.pkl")
    torch.save(StageCGRU().state_dict(), d / "stage_c.pt")
    export_state_dict(StageCGRU().state_dict(), d / "stage_c.npz")
    save_operating_point(POINT, d / "operating_point.json")
    return d


def test_live_scorer_runs_at_exactly_the_persisted_operating_point(model_dir):
    scorer = LiveScorer(model_dir)
    assert (scorer.weights.weight_a, scorer.weights.weight_b, scorer.weights.weight_c) == (0.15, 0.35, 0.5)
    assert scorer.threshold == 0.37
    assert load_operating_point(model_dir / "operating_point.json") == POINT


def test_missing_operating_point_raises_instead_of_defaulting(model_dir, tmp_path):
    for name in ("stage_b.json", "stage_b_calibrator.pkl", "stage_c.npz"):
        (tmp_path / name).write_bytes((model_dir / name).read_bytes())
    with pytest.raises(OperatingPointMissing):
        LiveScorer(tmp_path)


def test_missing_model_raises(model_dir, tmp_path):
    save_operating_point(POINT, tmp_path / "operating_point.json")
    with pytest.raises(ModelArtifactMissing):
        LiveScorer(tmp_path)


def test_operating_point_tuned_on_test_split_is_rejected(tmp_path):
    bad = OperatingPoint(**{**POINT.__dict__, "tuned_on": "test"})
    save_operating_point(bad, tmp_path / "operating_point.json")
    with pytest.raises(OperatingPointMissing):
        load_operating_point(tmp_path / "operating_point.json")


# --- handler against a real Postgres -------------------------------------

@pytest.fixture(scope="module")
def session_factory():
    with PostgresContainer("timescale/timescaledb:2.15.0-pg16") as container:
        conn = psycopg2.connect(host=container.get_container_host_ip(), port=container.get_exposed_port(5432),
                                user=container.username, password=container.password, dbname=container.dbname)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(INIT_SQL_PATH.read_text(encoding="utf-8"))
        conn.close()
        url = container.get_connection_url().replace("postgresql://", "postgresql+psycopg2://", 1)
        yield sessionmaker(bind=create_engine(url))


class FakeScorer:
    threshold = 0.5

    def __init__(self):
        self.next_fused = 0.0

    def score_message(self, message):
        f = self.next_fused
        return {"stage_a_score": 0.0, "stage_b_score": f, "stage_c_score": f, "fused_score": f, "raised": f >= self.threshold}

    def explain(self, message, scores):
        return {"source": "stage_b", "reasons": [{"feature": "deny_run_length", "shap_value": 1.0, "feature_value": 3}],
                "contributions": {}}


class FakeProducer:
    def __init__(self):
        self.messages = []

    def produce(self, topic, key=None, value=None):
        self.messages.append(json.loads(value))

    def flush(self, timeout=None):
        return 0


def _message(i: int, decision: str) -> bytes:
    seq = []
    for k in range(i + 1):
        ts = T0 + timedelta(seconds=30 * k)
        seq.append({"event_id": str(uuid.UUID(int=2 * k + 1)), "event_type": "mfa_prompt", "ts": ts.isoformat(),
                    "src_ip": "198.51.100.7", "device_id": "attacker", "user_agent": "x", "session_id": "s",
                    "ingest_ts": ts.isoformat()})
        dts = ts + timedelta(seconds=2)
        seq.append({"event_id": str(uuid.UUID(int=2 * k + 2)), "event_type": "mfa_decision", "ts": dts.isoformat(),
                    "decision": decision if k == i else "deny", "decision_latency_ms": 2000, "src_ip": "10.0.0.5",
                    "device_id": "phone", "user_agent": "y", "session_id": "s", "ingest_ts": dts.isoformat()})
    return json.dumps({"feature_vector": {"user_id": "victim", "n_prompts": i + 1}, "episode_id": "victim:ep1",
                       "session_id": "s", "decision_index": i, "sequence": seq}).encode()


def test_handler_upserts_one_alert_per_session_and_is_idempotent(session_factory):
    scorer, producer = FakeScorer(), FakeProducer()
    handler = EnrichedMessageHandler(scorer, session_factory, producer)

    scorer.next_fused = 0.2
    handler(_message(0, "deny"))
    scorer.next_fused = 0.7  # first crossing -> alert raised and published
    handler(_message(1, "deny"))
    handler(_message(1, "deny"))  # redelivery of the same message
    scorer.next_fused = 0.9  # capitulation approval inside the alerted session
    handler(_message(2, "approve"))

    db = session_factory()
    try:
        alerts = db.execute(text("SELECT fused_score, n_decisions, first_crossing_decision FROM alerts")).all()
        scores = db.execute(text("SELECT count(*) FROM scores")).scalar()
        events = db.execute(text("SELECT count(*) FROM events")).scalar()
    finally:
        db.close()
    assert alerts == [(0.9, 3, 1)]
    assert scores == 3  # redelivery did not duplicate the score row
    assert events == 6  # nor the events
    assert [m["reason"] for m in producer.messages] == ["raised", "approval_in_alerted_session"]
