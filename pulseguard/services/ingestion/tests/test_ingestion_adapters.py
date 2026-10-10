"""Telemetry adapters (REMEDIATION_TASK.md D1) and the mock IdP (D2)."""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import psycopg2
import pytest
from testcontainers.community.postgres import PostgresContainer

from services.ingestion.app.adapters.base import TelemetryAdapter
from services.ingestion.app.adapters.replay import ReplayAdapter, list_replayable_bursts
from services.ingestion.app.adapters.simulator import SimulatorSession

REPO_ROOT = Path(__file__).resolve().parents[3]
INIT_SQL_PATH = REPO_ROOT / "infra" / "postgres" / "init.sql"
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _episode(burst_id="u1:low_and_slow:1", user="u1", gap_minutes=25, n=3) -> pd.DataFrame:
    rows = []
    for i in range(n):
        p = T0 + timedelta(minutes=gap_minutes * i)
        base = dict(user_id=user, src_ip="203.0.113.9", device_id="atk", user_agent="x", session_id="s",
                    geo_country="US", burst_id=burst_id, label_attack=True, attack_profile="low_and_slow")
        rows.append({**base, "ts": p, "event_type": "mfa_prompt", "decision": None, "decision_latency_ms": None})
        rows.append({**base, "ts": p + timedelta(seconds=3), "event_type": "mfa_decision",
                     "decision": "deny" if i < n - 1 else "approve", "decision_latency_ms": 3000})
    return pd.DataFrame(rows)


class ListSink:
    def __init__(self):
        self.events = []

    def produce(self, event):
        self.events.append(event)

    def flush(self, timeout=10.0):
        return 0


def test_replay_and_simulator_are_both_telemetry_adapters():
    assert issubclass(ReplayAdapter, TelemetryAdapter)
    assert issubclass(SimulatorSession, TelemetryAdapter)


def test_preserve_mode_keeps_original_spacing_and_publishes_fast():
    sleeps = []
    adapter = ReplayAdapter(_episode(), "u1#ab", time_mode="preserve", pace_seconds=0.5, sleep=sleeps.append)
    sink = ListSink()
    assert adapter.run(sink) == 6
    ts = [e.ts for e in sink.events]
    assert (ts[2] - ts[0]) == timedelta(minutes=25)  # corpus gap preserved exactly
    assert ts[-1] <= datetime.now(timezone.utc)  # anchored to end "now", never in the future
    assert all(e.user_id == "u1#ab" for e in sink.events)
    assert all(e.ingest_ts == e.ts for e in sink.events)  # recorded episode: corpus ingest timing
    assert sleeps == [0.5] * 5


def test_realtime_mode_compresses_gaps_by_speedup():
    sleeps = []
    adapter = ReplayAdapter(_episode(), "u1#cd", time_mode="realtime", speedup=60.0, sleep=sleeps.append)
    sink = ListSink()
    adapter.run(sink)
    assert (sink.events[2].ts - sink.events[0].ts) == timedelta(seconds=25)


def test_list_replayable_bursts_summarises_episodes(tmp_path):
    df = pd.concat([_episode(), _episode("u2:high_volume_burst:2", "u2", gap_minutes=1, n=5)])
    df["attack_profile"] = df["burst_id"].str.split(":").str[1]
    path = tmp_path / "events.parquet"
    df.to_parquet(path)
    bursts = {b["burst_id"]: b for b in list_replayable_bursts(str(path))}
    assert bursts["u2:high_volume_burst:2"]["n_prompts"] == 5
    assert bursts["u2:high_volume_burst:2"]["n_denials"] == 4
    assert bursts["u1:low_and_slow:1"]["profile"] == "low_and_slow"
    only = list_replayable_bursts(str(path), profile="high_volume_burst")
    assert [b["burst_id"] for b in only] == ["u2:high_volume_burst:2"]


def test_simulator_measures_the_humans_real_reaction_time():
    sim = SimulatorSession(mode="attack", pacing_seconds=2.0)
    assert sim.send_prompt("attacker") is not None
    assert sim.send_prompt("attacker") is None  # one prompt at a time
    time.sleep(0.25)
    entry = sim.respond("deny")
    assert entry["latency_ms"] >= 250
    with pytest.raises(LookupError):
        sim.respond("approve")  # nothing pending
    sim.close()
    events = list(sim.events())
    assert [e.event_type.value for e in events] == ["mfa_prompt", "mfa_decision"]
    assert events[0].device_id != events[1].device_id  # attacker origin vs victim's phone
    assert events[1].decision_latency_ms == entry["latency_ms"]


def test_attacker_stops_pushing_once_the_idp_blocks_push():
    blocked = {"v": False}
    sim = SimulatorSession(mode="attack", pacing_seconds=2.0, is_push_blocked=lambda u: blocked["v"])
    blocked["v"] = True
    sim.attacker_loop()  # returns immediately: push is suspended
    assert sim.status == "protected"
    assert sim.prompts_sent == 0


# --- mock IdP against a real Postgres ---------------------------------------

@pytest.fixture(scope="module")
def ingestion_client():
    with PostgresContainer("timescale/timescaledb:2.15.0-pg16") as container:
        conn = psycopg2.connect(host=container.get_container_host_ip(), port=container.get_exposed_port(5432),
                                user=container.username, password=container.password, dbname=container.dbname)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(INIT_SQL_PATH.read_text(encoding="utf-8"))
        conn.close()
        env = {"POSTGRES_HOST": container.get_container_host_ip(), "POSTGRES_PORT": str(container.get_exposed_port(5432)),
               "POSTGRES_USER": container.username, "POSTGRES_PASSWORD": container.password,
               "POSTGRES_DB": container.dbname, "MITIGATION_URL": "http://127.0.0.1:9"}
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        import pulseguard_common.db.session as session_mod

        session_mod._engine = session_mod._SessionLocal = None
        from fastapi.testclient import TestClient

        from services.ingestion.app import main

        with TestClient(main.app) as client:
            yield client, main
        session_mod._engine = session_mod._SessionLocal = None
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_step_up_webhook_creates_a_challenge_that_blocks_push_until_resolved(ingestion_client):
    client, main = ingestion_client
    r = client.post("/idp/step-up", json={"user_id": "victim-1", "session_id": "victim-1:ep", "reason": "fused=0.9"})
    assert r.status_code == 200 and r.json()["accepted"] is True
    assert main._push_blocked("victim-1") is True
    challenge = client.get("/idp/challenges?user_id=victim-1").json()[0]
    assert challenge["kind"] == "step_up" and challenge["status"] == "pending"
    assert 10 <= challenge["number_match"] <= 99
    # the legitimate user passes the number match: push is honoured again
    r = client.post(f"/idp/challenges/{challenge['challenge_id']}/resolve", json={"passed": True})
    assert r.json()["status"] == "passed"
    assert main._push_blocked("victim-1") is False
    assert client.post(f"/idp/challenges/{challenge['challenge_id']}/resolve", json={"passed": True}).status_code == 409


def test_health_reports_adapters(ingestion_client):
    client, _ = ingestion_client
    body = client.get("/health").json()
    assert body["adapters"] == ["replay", "simulator"]
