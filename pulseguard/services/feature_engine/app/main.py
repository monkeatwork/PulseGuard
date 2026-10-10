"""L3 feature engine HTTP surface: health, and a read-only view of a user's
adaptive baseline (EWMA latency, cold-start state, known countries/devices,
open session) for the SOC dashboard.

The Faust worker (streaming_app.py) runs in the same container as a separate
process (run.sh); both talk to the same Redis.
"""

from __future__ import annotations

import os

import redis as redis_lib
from fastapi import FastAPI

from pulseguard_common.baseline_store import RedisBaselineStore
from pulseguard_common.cohort_fallback import COLD_START_THRESHOLD_EVENTS
from pulseguard_common.redis_keys import burst_current_key
from services.feature_engine.app.session_processor import decode_entry, describe_open_session

app = FastAPI(title="pulseguard-feature-engine")

_redis = redis_lib.Redis(host=os.environ.get("REDIS_HOST", "redis"), port=int(os.environ.get("REDIS_PORT", "6379")))


@app.get("/health")
def health() -> dict:
    try:
        redis_ok = bool(_redis.ping())
    except redis_lib.RedisError:
        redis_ok = False
    return {"status": "ok" if redis_ok else "degraded", "service": "feature_engine", "redis": redis_ok}


@app.get("/baselines/{user_id}")
def baseline(user_id: str) -> dict:
    store = RedisBaselineStore(_redis)
    latency = store.load_latency(user_id)
    buffered = [decode_entry(raw) for raw in _redis.lrange(burst_current_key(user_id), 0, -1)]
    return {
        "user_id": user_id,
        "latency_mean_ms": latency.mean_ms,
        "latency_std_ms": latency.std_ms,
        "event_count": latency.event_count,
        "cold_start": latency.is_cold_start,
        "cold_start_threshold": COLD_START_THRESHOLD_EVENTS,
        "known_countries": sorted(store.known_countries(user_id)),
        "known_devices": sorted(store.known_devices(user_id)),
        "open_session": describe_open_session(buffered),
    }
