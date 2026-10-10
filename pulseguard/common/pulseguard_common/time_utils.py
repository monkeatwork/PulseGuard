"""Time helpers shared across services.

Centralizes the clock-skew tolerance used by the feature engine so the
threshold is defined once (see DECISIONS.md, "latency_drift_slope edge cases").
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

CLOCK_SKEW_TOLERANCE_SECONDS = 2.0
OUT_OF_ORDER_GRACE_SECONDS = 5.0
BURST_GAP_THRESHOLD_SECONDS = 5 * 60
BURST_WINDOW_SECONDS = 10 * 60
LATENCY_DRIFT_HOP_SECONDS = 60


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def is_clock_skewed(ts: datetime, ingest_ts: datetime, rolling_median_skew_seconds: float) -> bool:
    """True if this event's ingest/issue gap deviates from the user's rolling
    median skew by more than CLOCK_SKEW_TOLERANCE_SECONDS."""
    observed_skew = (ingest_ts - ts).total_seconds()
    return abs(observed_skew - rolling_median_skew_seconds) > CLOCK_SKEW_TOLERANCE_SECONDS


def within_grace_window(event_ts: datetime, burst_finalized_at: datetime) -> bool:
    return event_ts <= burst_finalized_at + timedelta(seconds=OUT_OF_ORDER_GRACE_SECONDS)
