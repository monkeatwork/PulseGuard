"""Integration test (real Redis via Testcontainers): the baseline store's
state must persist across a service restart (Phase 3 gate) — simulated
here by constructing a brand new RedisBaselineStore instance backed by the
same Redis container, exactly as a redeployed feature-engine pod would."""

from __future__ import annotations

import redis as redis_lib
import pytest
from testcontainers.community.redis import RedisContainer

from pulseguard_common.baseline_store import RedisBaselineStore


@pytest.fixture(scope="module")
def redis_client():
    with RedisContainer("redis:7.2-alpine") as container:
        client = redis_lib.Redis(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(6379)),
        )
        yield client


@pytest.fixture(autouse=True)
def _flush_between_tests(redis_client):
    redis_client.flushall()
    yield


def test_latency_baseline_persists_across_store_restart(redis_client):
    user_id = "user-restart-test"
    store_a = RedisBaselineStore(redis_client)
    store_a.update_latency(user_id, 5000.0)
    store_a.update_latency(user_id, 6000.0)
    store_a.update_latency(user_id, 4000.0)

    # Simulate a service restart: a fresh store instance, same Redis backend.
    store_b = RedisBaselineStore(redis_client)
    restored = store_b.load_latency(user_id)

    assert restored.event_count == 3
    assert restored.mean_ms > 0
    assert restored.std_ms > 0


def test_latency_baseline_continues_updating_after_restore(redis_client):
    user_id = "user-continue-test"
    store_a = RedisBaselineStore(redis_client)
    store_a.update_latency(user_id, 5000.0)
    mean_before = store_a.load_latency(user_id).mean_ms

    store_b = RedisBaselineStore(redis_client)
    updated = store_b.update_latency(user_id, 1000.0)

    assert updated.event_count == 2
    assert updated.mean_ms != mean_before


def test_rate_baseline_persists_independently_of_latency(redis_client):
    user_id = "user-rate-test"
    store = RedisBaselineStore(redis_client)
    store.update_latency(user_id, 5000.0)
    store.update_rate(user_id, 3600.0)

    latency = store.load_latency(user_id)
    rate = store.load_rate(user_id)
    assert latency.event_count == 1
    assert rate.mean_seconds > 0


def test_new_user_has_empty_baseline():
    from unittest.mock import MagicMock

    fake_redis = MagicMock()
    fake_redis.get.return_value = None
    store = RedisBaselineStore(fake_redis)
    baseline = store.load_latency("brand-new-user")
    assert baseline.event_count == 0
    assert baseline.is_cold_start is True


def test_device_and_country_novelty_tracking(redis_client):
    user_id = "user-novelty-test"
    store = RedisBaselineStore(redis_client)

    assert store.is_country_known(user_id, "US") is False
    store.record_country(user_id, "US")
    assert store.is_country_known(user_id, "US") is True
    assert store.is_country_known(user_id, "FR") is False

    assert store.is_device_known(user_id, "device-1") is False
    store.record_device(user_id, "device-1")
    assert store.is_device_known(user_id, "device-1") is True

    assert store.known_countries(user_id) == {"US"}
    assert store.known_devices(user_id) == {"device-1"}
