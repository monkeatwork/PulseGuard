"""Integration tests (real Postgres via Testcontainers, real local HTTP
server for the webhook round trip) — Phase 6 gate: "full webhook round
trip against a mocked IdP endpoint," plus proving `mitigation_actions`
persists against the real schema in infra/postgres/init.sql.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import psycopg2
import pytest
from testcontainers.community.postgres import PostgresContainer

from services.mitigation.app.webhook_client import StepUpWebhookClient

REPO_ROOT = Path(__file__).resolve().parents[3]
INIT_SQL_PATH = REPO_ROOT / "infra" / "postgres" / "init.sql"


@pytest.fixture(scope="module")
def postgres_container():
    with PostgresContainer("timescale/timescaledb:2.15.0-pg16") as container:
        conn = psycopg2.connect(
            host=container.get_container_host_ip(),
            port=container.get_exposed_port(5432),
            user=container.username,
            password=container.password,
            dbname=container.dbname,
        )
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(INIT_SQL_PATH.read_text(encoding="utf-8"))
        yield conn
        conn.close()


class _MockIdpHandler(BaseHTTPRequestHandler):
    received_requests: list[dict] = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        _MockIdpHandler.received_requests.append({"path": self.path, "body": body})
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, format, *args):
        pass  # silence default request logging


@pytest.fixture(scope="module")
def mock_idp_server():
    server = HTTPServer(("127.0.0.1", 0), _MockIdpHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_mitigation_actions_table_round_trips_a_real_row(postgres_container):
    alert_id = uuid.uuid4()
    action_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    with postgres_container.cursor() as cur:
        cur.execute(
            """
            INSERT INTO alerts (alert_id, user_id, ts, updated_ts, fused_score)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (str(alert_id), "user1", now, now, 0.93),
        )
        cur.execute(
            """
            INSERT INTO mitigation_actions
                (action_id, user_id, ts, action_type, alert_id, consecutive_failures)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (str(action_id), "user1", now, "step_up_required", str(alert_id), 0),
        )

        cur.execute("SELECT action_type, consecutive_failures FROM mitigation_actions WHERE action_id = %s", (str(action_id),))
        row = cur.fetchone()

    assert row == ("step_up_required", 0)


def test_mitigation_actions_rejects_invalid_action_type(postgres_container):
    with pytest.raises(psycopg2.Error):
        with postgres_container.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mitigation_actions (action_id, user_id, ts, action_type, consecutive_failures)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (str(uuid.uuid4()), "user2", datetime.now(timezone.utc), "locked", 0),
            )
    postgres_container.rollback()


def test_full_webhook_round_trip_against_a_real_local_server(mock_idp_server):
    _MockIdpHandler.received_requests.clear()
    client = StepUpWebhookClient(mock_idp_server)

    result = client.trigger_step_up("user1", "session1", "fused score 0.93 exceeded threshold")

    assert result is True
    assert len(_MockIdpHandler.received_requests) == 1
    request = _MockIdpHandler.received_requests[0]
    assert request["path"] == "/step-up"
    assert request["body"]["user_id"] == "user1"
    assert request["body"]["session_id"] == "session1"


def test_full_alt_factor_webhook_round_trip(mock_idp_server):
    _MockIdpHandler.received_requests.clear()
    client = StepUpWebhookClient(mock_idp_server)

    result = client.trigger_alt_factor("user2", "session2", "escalated after 3 failures")

    assert result is True
    assert _MockIdpHandler.received_requests[0]["path"] == "/alt-factor"
