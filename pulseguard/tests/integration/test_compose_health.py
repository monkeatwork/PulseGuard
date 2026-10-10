"""End-to-end gate: a clean checkout comes up with `docker compose up` (what
./run.sh does) with every health check green, and a replayed attack flows
through the whole pipeline -- ingestion -> Kafka -> feature engine ->
detection -> mitigation -> mock IdP -- to an alert and a step-up challenge.

Requires Docker. Everything is reached the way a user reaches it: through
the dashboard's nginx on the one published port, plus `docker compose exec`
for the infrastructure checks (Postgres, Redis and Kafka are deliberately
not published to the host).

WARNING -- DESTRUCTIVE to a running stack: teardown is
`docker compose down --volumes`, which deletes every alert/event row. That
is correct for a "clean checkout" gate; do not run it against data you want
to keep (./run.sh starts fresh anyway).
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pytest
from testcontainers.compose import DockerCompose

REPO_ROOT = Path(__file__).resolve().parents[2]
STARTUP_TIMEOUT_SECONDS = 180
DASHBOARD = "http://localhost:3000"
API_HEALTH = ["ingestion", "features", "detection", "mitigation"]


def _get(path: str, timeout: float = 5.0):
    with urllib.request.urlopen(f"{DASHBOARD}{path}", timeout=timeout) as resp:
        return json.loads(resp.read())


def _post(path: str, body: dict):
    req = urllib.request.Request(f"{DASHBOARD}{path}", data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _wait(predicate, timeout: float, what: str):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except Exception as exc:  # noqa: BLE001 -- retry loop
            last = exc
        time.sleep(2)
    raise TimeoutError(f"{what} not reached in {timeout}s") from last


def _exec(service: str, *cmd: str) -> str:
    return subprocess.run(
        ["docker", "compose", "exec", "-T", service, *cmd], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture(scope="module")
def compose_stack():
    with DockerCompose(str(REPO_ROOT), compose_file_name="docker-compose.yml", pull=False, wait=True) as stack:
        yield stack


def test_every_service_api_is_healthy_through_the_dashboard(compose_stack):
    for api in API_HEALTH:
        _wait(lambda: _get(f"/api/{api}/health")["status"] == "ok", STARTUP_TIMEOUT_SECONDS, f"{api} health")


def test_postgres_has_timescaledb_and_the_schema(compose_stack):
    out = _exec("postgres", "psql", "-U", "pulseguard", "-d", "pulseguard", "-tAc",
                "SELECT extname FROM pg_extension WHERE extname='timescaledb'")
    assert out.strip() == "timescaledb"
    tables = _exec("postgres", "psql", "-U", "pulseguard", "-d", "pulseguard", "-tAc",
                   "SELECT string_agg(tablename, ',' ORDER BY tablename) FROM pg_tables WHERE schemaname='public'")
    for table in ("alerts", "events", "scores", "mitigation_actions", "idp_challenges", "scenario_runs", "dead_letters"):
        assert table in tables


def test_redis_and_kafka_topics(compose_stack):
    assert _exec("redis", "redis-cli", "ping").strip() == "PONG"
    topics = _exec("ingestion", "python", "-c",
                   "from confluent_kafka.admin import AdminClient;"
                   "print(sorted(AdminClient({'bootstrap.servers':'kafka:9092'}).list_topics(timeout=10).topics))")
    for topic in ("pulseguard.events.raw", "pulseguard.events.enriched", "pulseguard.alerts", "pulseguard.dlq"):
        assert topic in topics


def test_replayed_attack_is_alerted_and_stepped_up(compose_stack):
    _wait(lambda: _get("/api/ingestion/health")["status"] == "ok", STARTUP_TIMEOUT_SECONDS, "ingestion")
    burst = _get("/api/ingestion/scenarios?profile=high_volume_burst&limit=1")[0]["burst_id"]
    run = _post("/api/ingestion/scenarios/replay", {"burst_id": burst, "pace_seconds": 0.1})
    user = run["user_id"]
    alert = _wait(lambda: next((a for a in _get("/api/detection/alerts") if a["user_id"] == user), None), 120, "alert")
    assert alert["scenario"]["profile"] == "high_volume_burst"
    challenge = _wait(lambda: next((c for c in _get(f"/api/ingestion/idp/challenges?user_id={urllib.parse.quote(user)}")), None), 60,
                      "step-up challenge")
    assert challenge["kind"] == "step_up"
