"""Phase 0 gate: `docker compose up` brings up every container with all
health checks green within 90s, with zero manual setup steps.

Requires Docker to be running. Uses testcontainers' DockerCompose wrapper
to drive the same docker-compose.yml a developer would run directly.

WARNING -- this test is DESTRUCTIVE to a running stack. testcontainers'
`DockerCompose.stop()` tears down with `docker compose down --volumes`,
which deletes the `pg_data` named volume: every `alerts`, `events` and
`mitigation_actions` row from any live pipeline run is gone afterwards,
and the stack is left down entirely (`docker compose up -d` to restore).
That teardown is correct for what this test asserts -- the Phase 0 gate is
specifically "a CLEAN checkout comes up with zero manual steps", which a
pre-warmed volume would invalidate -- so the behaviour is deliberately
left as-is rather than softened to `down` without `--volumes`. Do not run
this test against a stack whose data you want to keep.
"""

from __future__ import annotations

import socket
import time
from pathlib import Path

import psycopg2
import pytest
import redis
from testcontainers.compose import DockerCompose

REPO_ROOT = Path(__file__).resolve().parents[2]
STARTUP_TIMEOUT_SECONDS = 90

HTTP_HEALTH_SERVICES = {
    "ingestion": 8001,
    "feature_engine": 8002,
    "detection_engine": 8003,
    "mitigation": 8004,
}

# These are the HOST-published ports from docker-compose.yml, which are
# deliberately not the same as the in-container ports the services use to
# talk to each other. Redis publishes 6380 (6379 is commonly already taken
# by a local Redis or another project's container), and Redpanda's
# host-reachable listener is the `external` one on 19092 -- 9092 is the
# internal listener, whose advertised address (`redpanda:9092`) only
# resolves inside the compose network. Keep these in sync with
# docker-compose.yml; a mismatch here fails as a connection timeout, which
# looks like a broken container rather than a wrong port number.
REDIS_HOST_PORT = 6380
REDPANDA_HOST_PORT = 19092


def _wait_for_tcp(host: str, port: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2):
                return
        except OSError as exc:
            last_error = exc
            time.sleep(2)
    raise TimeoutError(f"{host}:{port} did not become reachable in {timeout}s") from last_error


def _wait_for_http_health(port: int, timeout: float) -> None:
    import urllib.request

    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://localhost:{port}/health", timeout=2) as resp:
                if resp.status == 200:
                    return
        except Exception as exc:  # noqa: BLE001 - retry loop, re-raised on timeout
            last_error = exc
            time.sleep(2)
    raise TimeoutError(f"port {port} /health did not return 200 in {timeout}s") from last_error


@pytest.fixture(scope="module")
def compose_stack():
    with DockerCompose(str(REPO_ROOT), compose_file_name="docker-compose.yml", pull=False) as stack:
        yield stack


def test_all_service_health_endpoints_respond(compose_stack):
    for _service, port in HTTP_HEALTH_SERVICES.items():
        _wait_for_http_health(port, STARTUP_TIMEOUT_SECONDS)


def test_postgres_has_timescaledb_extension(compose_stack):
    _wait_for_tcp("localhost", 5432, STARTUP_TIMEOUT_SECONDS)
    conn = psycopg2.connect(
        host="localhost",
        port=5432,
        user="pulseguard",
        password="pulseguard_dev_password",
        dbname="pulseguard",
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT extname FROM pg_extension WHERE extname = 'timescaledb'")
            assert cur.fetchone() is not None
    finally:
        conn.close()


def test_redis_ping_succeeds(compose_stack):
    _wait_for_tcp("localhost", REDIS_HOST_PORT, STARTUP_TIMEOUT_SECONDS)
    client = redis.Redis(host="localhost", port=REDIS_HOST_PORT)
    assert client.ping() is True


def test_redpanda_topic_creation_succeeds(compose_stack):
    _wait_for_tcp("localhost", REDPANDA_HOST_PORT, STARTUP_TIMEOUT_SECONDS)
    from confluent_kafka.admin import AdminClient, NewTopic

    admin = AdminClient({"bootstrap.servers": f"localhost:{REDPANDA_HOST_PORT}"})
    topic = "pulseguard.events.raw"
    # 1 partition, matching the corrected Phase 0 decision recorded in
    # DECISIONS.md: a single Faust worker requires its table to co-partition
    # with this topic, so the original forward-looking 6 was reduced to 1.
    futures = admin.create_topics([NewTopic(topic, num_partitions=1, replication_factor=1)])
    for created_topic, future in futures.items():
        try:
            future.result(timeout=30)
        except Exception as exc:  # noqa: BLE001
            if "TOPIC_ALREADY_EXISTS" not in str(exc):
                raise
    metadata = admin.list_topics(timeout=10)
    assert topic in metadata.topics
