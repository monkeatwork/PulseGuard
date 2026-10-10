"""Tests the detection_engine dashboard API against a real Postgres
(Testcontainers, the actual infra/postgres/init.sql schema) — proving the
API layer and schema are correct independent of whether the live Faust
pipeline is wired to populate them yet (see main.py's module docstring).
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from testcontainers.community.postgres import PostgresContainer

from pulseguard_common.db.session import get_db

os.environ["LIVE_SCORER"] = "off"  # API-only tests; the worker is covered in test_live_scorer.py
from services.detection_engine.app.main import app  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
INIT_SQL_PATH = REPO_ROOT / "infra" / "postgres" / "init.sql"

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def session_factory():
    with PostgresContainer("timescale/timescaledb:2.15.0-pg16") as container:
        raw_conn = psycopg2.connect(
            host=container.get_container_host_ip(),
            port=container.get_exposed_port(5432),
            user=container.username,
            password=container.password,
            dbname=container.dbname,
        )
        raw_conn.autocommit = True
        with raw_conn.cursor() as cur:
            cur.execute(INIT_SQL_PATH.read_text(encoding="utf-8"))
        raw_conn.close()

        url = container.get_connection_url().replace("postgresql://", "postgresql+psycopg2://", 1)
        engine = create_engine(url)
        yield sessionmaker(bind=engine)


@pytest.fixture()
def client(session_factory):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _clean_tables(session_factory):
    db = session_factory()
    for table in ("mitigation_actions", "alerts", "events", "scores", "scenario_runs", "idp_challenges", "dead_letters"):
        db.execute(text(f"DELETE FROM {table}"))
    db.commit()
    db.close()
    yield


def _insert_alert(session_factory, alert_id, user_id, ts, fused_score, shap_top3=None, burst_id=None):
    db = session_factory()
    db.execute(
        text(
            """
            INSERT INTO alerts (alert_id, user_id, ts, updated_ts, fused_score, shap_top3, burst_id)
            VALUES (:alert_id, :user_id, :ts, :ts, :fused_score, CAST(:shap_top3 AS JSONB), :burst_id)
            """
        ),
        {
            "alert_id": str(alert_id),
            "user_id": user_id,
            "ts": ts,
            "fused_score": fused_score,
            "shap_top3": json.dumps(shap_top3) if shap_top3 is not None else None,
            "burst_id": burst_id,
        },
    )
    db.commit()
    db.close()


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_list_alerts_returns_inserted_rows(client, session_factory):
    alert_id = uuid.uuid4()
    _insert_alert(session_factory, alert_id, "user1", T0, 0.87)

    response = client.get("/alerts")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["user_id"] == "user1"
    assert body[0]["fused_score"] == 0.87


def test_list_alerts_orders_newest_first(client, session_factory):
    _insert_alert(session_factory, uuid.uuid4(), "older", T0, 0.5)
    _insert_alert(session_factory, uuid.uuid4(), "newer", T0 + timedelta(hours=1), 0.6)

    response = client.get("/alerts")
    body = response.json()
    assert body[0]["user_id"] == "newer"
    assert body[1]["user_id"] == "older"


def test_get_alert_detail_includes_shap_and_sequence(client, session_factory):
    alert_id = uuid.uuid4()
    session_id = "session-abc"
    shap = [{"feature": "latency_drift_slope", "shap_value": -1.2, "feature_value": -800.0}]
    _insert_alert(session_factory, alert_id, "user1", T0, 0.9, shap_top3=shap, burst_id=session_id)

    db = session_factory()
    db.execute(
        text(
            """
            INSERT INTO events (event_id, user_id, ts, event_type, decision, decision_latency_ms,
                                 src_ip, device_id, user_agent, session_id, episode_id, ingest_ts)
            VALUES (:eid, :uid, :ts, 'mfa_decision', 'deny', 3000, '10.0.0.1', 'd1', 'ua', 'idp-s', :sid, :ts)
            """
        ),
        {"eid": str(uuid.uuid4()), "uid": "user1", "ts": T0, "sid": session_id},
    )
    db.commit()
    db.close()

    response = client.get(f"/alerts/{alert_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["shap_top3"] == shap
    assert len(body["sequence"]) == 1
    assert body["sequence"][0]["decision"] == "deny"


def test_get_alert_detail_404_for_unknown_id(client):
    response = client.get(f"/alerts/{uuid.uuid4()}")
    assert response.status_code == 404


def test_export_cef_returns_well_formed_line(client, session_factory):
    alert_id = uuid.uuid4()
    _insert_alert(session_factory, alert_id, "user1", T0, 0.93)

    response = client.get(f"/alerts/{alert_id}/cef")
    assert response.status_code == 200
    assert response.text.startswith("CEF:0|PulseGuard|")
    assert "suser=user1" in response.text


def test_alert_status_can_be_triaged(client, session_factory):
    alert_id = uuid.uuid4()
    _insert_alert(session_factory, alert_id, "user1", T0, 0.9)
    response = client.patch(f"/alerts/{alert_id}", json={"status": "acknowledged"})
    assert response.status_code == 200
    assert client.get(f"/alerts/{alert_id}").json()["status"] == "acknowledged"
    assert client.patch(f"/alerts/{alert_id}", json={"status": "deleted"}).status_code == 422


def test_stats_and_recent_scores(client, session_factory):
    db = session_factory()
    for i, ms in enumerate([2.0, 4.0, 6.0]):
        db.execute(
            text(
                """INSERT INTO scores (ts, user_id, episode_id, decision_index, decision, decision_latency_ms,
                   stage_a_score, stage_b_score, stage_c_score, fused_score, threshold, raised, scoring_ms)
                   VALUES (:ts, 'u', 'ep', :i, 'deny', 1000, 0, 0.1, 0.2, 0.15, 0.5, false, :ms)"""
            ),
            {"ts": T0 + timedelta(seconds=i), "i": i, "ms": ms},
        )
    db.commit()
    db.close()
    stats = client.get("/stats").json()
    assert stats["decisions_scored"] == 3
    assert stats["sessions_scored"] == 1
    assert stats["scoring_ms_p50"] == 4.0
    recent = client.get("/scores/recent?limit=2").json()
    assert [r["decision_index"] for r in recent] == [2, 1]


def test_eval_results_are_served_verbatim(client):
    body = client.get("/eval/results").json()
    assert isinstance(body, dict)
