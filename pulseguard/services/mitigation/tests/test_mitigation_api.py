"""Tests the mitigation dashboard API (GET /actions) against a real
Postgres (Testcontainers, the actual infra/postgres/init.sql schema)."""

from __future__ import annotations

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

os.environ["MITIGATION_WORKER"] = "off"  # API-only; the worker's handler is tested directly
from services.mitigation.app.main import app  # noqa: E402

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
    db.execute(text("DELETE FROM mitigation_actions"))
    db.commit()
    db.close()
    yield


def _insert_action(session_factory, user_id, ts, action_type, consecutive_failures=0):
    db = session_factory()
    db.execute(
        text(
            """
            INSERT INTO mitigation_actions (action_id, user_id, ts, action_type, consecutive_failures)
            VALUES (:action_id, :user_id, :ts, :action_type, :failures)
            """
        ),
        {
            "action_id": str(uuid.uuid4()),
            "user_id": user_id,
            "ts": ts,
            "action_type": action_type,
            "failures": consecutive_failures,
        },
    )
    db.commit()
    db.close()


def test_list_actions_filters_by_user(client, session_factory):
    _insert_action(session_factory, "user1", T0, "step_up_required")
    _insert_action(session_factory, "user2", T0, "alt_factor_required")

    response = client.get("/actions?user_id=user1")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["user_id"] == "user1"
    assert body[0]["action_type"] == "step_up_required"


def test_list_actions_orders_newest_first(client, session_factory):
    _insert_action(session_factory, "user1", T0, "step_up_required", consecutive_failures=1)
    _insert_action(session_factory, "user1", T0 + timedelta(minutes=10), "alt_factor_required", consecutive_failures=3)

    response = client.get("/actions?user_id=user1")
    body = response.json()
    assert body[0]["action_type"] == "alt_factor_required"
    assert body[0]["consecutive_failures"] == 3
    assert body[1]["action_type"] == "step_up_required"


def test_list_actions_empty_for_unknown_user(client):
    response = client.get("/actions?user_id=nobody")
    assert response.status_code == 200
    assert response.json() == []


def test_feedback_failures_escalate_and_a_pass_resets(client):
    for _ in range(3):
        body = client.post("/feedback", json={"user_id": "fb-user", "passed": False}).json()
    assert len(body["recent_failures"]) == 3
    state = client.get("/state/fb-user").json()
    assert state["policy"]["lockout_possible"] is False
    body = client.post("/feedback", json={"user_id": "fb-user", "passed": True}).json()
    assert body["recent_failures"] == []


def test_alert_handler_links_action_to_alert_and_escalates_without_lockout(session_factory):
    """End-to-end through the worker's handler with a real schema: first
    alert -> step-up; failed step-ups reported by the IdP -> alt factor once
    the cooldown passes; never anything else."""
    import json as _json

    from services.mitigation.app.controller import UserMitigationState
    from services.mitigation.app.live_worker import AlertHandler, UserStates

    class Webhook:
        def __init__(self):
            self.calls = []

        def trigger_step_up(self, user_id, session_id, reason):
            self.calls.append("step_up")
            return True

        def trigger_alt_factor(self, user_id, session_id, reason):
            self.calls.append("alt_factor")
            return True

    db = session_factory()
    alert_id = uuid.uuid4()
    db.execute(text("INSERT INTO alerts (alert_id, user_id, ts, updated_ts, fused_score) VALUES (:a, 'h-user', now(), now(), 0.9)"),
               {"a": str(alert_id)})
    db.commit()
    db.close()

    states, webhook = UserStates(), Webhook()
    handler = AlertHandler(session_factory, webhook, states)
    msg = _json.dumps({"alert_id": str(alert_id), "user_id": "h-user", "fused_score": 0.9}).encode()
    assert handler(msg) == "step_up_required"
    assert handler(msg) == "cooldown_active"
    # three failed step-ups, then the cooldown lapses
    state: UserMitigationState = states.get("h-user")
    now = datetime.now(timezone.utc)
    for _ in range(3):
        state.record_failure(now)
    state.last_step_up_ts = now - timedelta(hours=1)
    assert handler(msg) == "alt_factor_required"
    assert webhook.calls == ["step_up", "alt_factor"]

    db = session_factory()
    rows = db.execute(text("SELECT action_type, alert_id FROM mitigation_actions WHERE user_id='h-user' ORDER BY ts")).all()
    db.close()
    assert [r[0] for r in rows] == ["step_up_required", "cooldown_active", "alt_factor_required"]
    assert all(str(r[1]) == str(alert_id) for r in rows)
    # a below-threshold alert is not even considered
    low = _json.dumps({"alert_id": str(alert_id), "user_id": "h-user", "fused_score": 0.01}).encode()
    assert handler(low) is None
