"""Redis key layout, per DECISIONS.md "Redis key layout" (2026-09-20).

All keys are namespaced under `pg:` so they can be scanned/flushed as a group
in tests without touching other applications sharing the same Redis instance.
"""

from __future__ import annotations

BURST_KEY_TTL_SECONDS = 15 * 60


def baseline_latency_key(user_id: str) -> str:
    return f"pg:baseline:{user_id}:latency"


def baseline_rate_key(user_id: str) -> str:
    return f"pg:baseline:{user_id}:rate"


def burst_current_key(user_id: str) -> str:
    return f"pg:burst:{user_id}:current"


def cohort_latency_key(cohort_id: str) -> str:
    return f"pg:cohort:{cohort_id}:latency"


def known_countries_key(user_id: str) -> str:
    """Native Redis SET (SADD/SISMEMBER), not pickled — see DECISIONS.md,
    Phase 3 feature-engine design choices, for why novelty tracking gets its
    own keys separate from the numeric latency/rate baselines."""
    return f"pg:novelty:{user_id}:countries"


def known_devices_key(user_id: str) -> str:
    return f"pg:novelty:{user_id}:devices"
