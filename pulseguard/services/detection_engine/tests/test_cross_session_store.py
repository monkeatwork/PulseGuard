"""The Redis-backed guard (real Redis via Testcontainers) gives the same
answer as the pure streaming guard, is idempotent under redelivery, trims
by event time, and only runs at a validation-selected config."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
import redis as redis_lib
from testcontainers.community.redis import RedisContainer

from pulseguard_common.redis_keys import guard_denials_key
from services.detection_engine.app.cross_session_guard import CrossSessionGuardConfig, DenialHistory, observe
from services.detection_engine.app.cross_session_store import (
    GuardConfigMissing,
    RedisDenialStore,
    config_from_results,
    load_guard_config,
    save_guard_config,
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
CFG = CrossSessionGuardConfig(min_denials=3, window_seconds=24 * 3600, resolve_seconds=600)


@pytest.fixture(scope="module")
def redis_client():
    with RedisContainer("redis:7.2-alpine") as container:
        yield redis_lib.Redis(host=container.get_container_host_ip(), port=int(container.get_exposed_port(6379)))


@pytest.fixture(autouse=True)
def _flush(redis_client):
    redis_client.flushall()


def test_store_matches_the_pure_streaming_guard(redis_client):
    store = RedisDenialStore(redis_client, CFG)
    rng = np.random.default_rng(3)
    history, ts = DenialHistory(), T0
    for i in range(300):
        ts += timedelta(minutes=int(rng.integers(1, 400)))
        decision = "deny" if rng.random() < 0.5 else "approve"
        count = store.record("u", ts, decision, f"e{i}")
        assert store.fired(count) == observe(history, ts, decision, CFG), i


def test_slow_attack_fires_on_the_capitulation_approval(redis_client):
    store = RedisDenialStore(redis_client, CFG)
    counts = [store.record("victim", T0 + timedelta(hours=2 * k), d, f"e{k}")
              for k, d in enumerate(["deny", "deny", "deny", "approve"])]
    assert counts == [0, 1, 2, 3]
    assert store.fired(counts[-1])


def test_redelivery_does_not_double_count(redis_client):
    store = RedisDenialStore(redis_client, CFG)
    for k in range(2):
        store.record("u", T0 + timedelta(hours=k), "deny", f"e{k}")
        store.record("u", T0 + timedelta(hours=k), "deny", f"e{k}")  # redelivered
    assert store.record("u", T0 + timedelta(hours=3), "approve", "e9") == 2


def test_entries_are_trimmed_by_event_time(redis_client):
    store = RedisDenialStore(redis_client, CFG)
    store.record("u", T0, "deny", "old")
    store.record("u", T0 + timedelta(seconds=CFG.horizon_seconds + 60), "deny", "new")
    assert [m.decode() for m in redis_client.zrange(guard_denials_key("u"), 0, -1)] == ["new"]
    assert redis_client.ttl(guard_denials_key("u")) > 0


def test_config_round_trips_and_must_be_selected_on_val(tmp_path):
    results = {"chosen": "K=3, window=7d", "chosen_config": {"min_denials": 3, "window_seconds": 604800, "resolve_seconds": 600},
               "seed": 42, "scale": 1000,
               "selection": {"stray_rate": 0.1, "val_fpr_budget": 0.002, "slow_gaps_seconds": [7200]}}
    config, provenance = config_from_results(results)
    save_guard_config(config, tmp_path / "g.json", provenance)
    assert load_guard_config(tmp_path / "g.json") == config

    raw = json.loads((tmp_path / "g.json").read_text())
    raw["provenance"]["selected_on"] = "test"
    (tmp_path / "g.json").write_text(json.dumps(raw))
    with pytest.raises(GuardConfigMissing):
        load_guard_config(tmp_path / "g.json")
    with pytest.raises(GuardConfigMissing):
        load_guard_config(tmp_path / "missing.json")
