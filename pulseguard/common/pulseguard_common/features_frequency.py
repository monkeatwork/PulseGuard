"""Frequency features (CLAUDE.md feature table): established UEBA building
blocks. All functions are pure — no I/O, no Redis, no Kafka — taking
already-resolved baseline/context values as plain arguments so they are
unit-testable in isolation from the stream (CLAUDE.md, "Working
conventions").
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from statistics import mean, pstdev
from typing import Optional

from pulseguard_common.time_utils import BURST_WINDOW_SECONDS

# Off-hours window in UTC. A real deployment would use the user's local
# timezone; the RBA dataset carries no timezone/offset field (only
# country/ASN), so this is a documented simplification, not a resolved
# question — see DECISIONS.md, "Off-hours window and impossible-travel
# fallback use UTC/country-level proxies".
OFF_HOURS_START_HOUR_UTC = 0
OFF_HOURS_END_HOUR_UTC = 6

# Above this implied ground speed between two consecutive logins, travel is
# physically impossible (commercial flight cruise speed, generously rounded
# up as a conservative threshold to minimize false positives).
MAX_PLAUSIBLE_TRAVEL_SPEED_KMH = 1000.0
EARTH_RADIUS_KM = 6371.0


def prompts_per_window(
    prompt_timestamps: list[datetime],
    as_of: datetime,
    window_seconds: float = BURST_WINDOW_SECONDS,
) -> int:
    """Count of prompts in (as_of - window_seconds, as_of]."""
    return sum(
        1 for ts in prompt_timestamps if 0 <= (as_of - ts).total_seconds() <= window_seconds
    )


def inter_prompt_mean(prompt_timestamps: list[datetime]) -> Optional[float]:
    if len(prompt_timestamps) < 2:
        return None
    ordered = sorted(prompt_timestamps)
    gaps = [(b - a).total_seconds() for a, b in zip(ordered, ordered[1:])]
    return mean(gaps)


def inter_prompt_std(prompt_timestamps: list[datetime]) -> Optional[float]:
    if len(prompt_timestamps) < 2:
        return None
    ordered = sorted(prompt_timestamps)
    gaps = [(b - a).total_seconds() for a, b in zip(ordered, ordered[1:])]
    if len(gaps) < 2:
        return 0.0
    return pstdev(gaps)


def burst_duration_seconds(prompt_timestamps: list[datetime]) -> float:
    if not prompt_timestamps:
        return 0.0
    ordered = sorted(prompt_timestamps)
    return (ordered[-1] - ordered[0]).total_seconds()


def off_hours_flag(ts: datetime) -> bool:
    hour = ts.astimezone(timezone.utc).hour
    return OFF_HOURS_START_HOUR_UTC <= hour < OFF_HOURS_END_HOUR_UTC


def geo_novelty(current_country: Optional[str], known_countries: set[str]) -> bool:
    """True if `current_country` has never been seen for this user before."""
    if not current_country:
        return False
    return current_country not in known_countries


def device_novelty(current_device_id: str, known_devices: set[str]) -> bool:
    return current_device_id not in known_devices


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def impossible_travel(
    prev_ts: datetime,
    prev_lat: Optional[float],
    prev_lon: Optional[float],
    prev_country: Optional[str],
    curr_ts: datetime,
    curr_lat: Optional[float],
    curr_lon: Optional[float],
    curr_country: Optional[str],
) -> bool:
    """True latency implies faster-than-physically-possible travel between
    two consecutive logins. Uses haversine distance when both events carry
    coordinates; falls back to a coarser "different country within under an
    hour" heuristic when lat/lon is unavailable (as is the case for every
    RBA-derived benign event — see DECISIONS.md, "Geo lat/lon made
    optional"). The fallback is intentionally conservative (a wide time
    margin) since it cannot bound actual distance."""
    elapsed_hours = (curr_ts - prev_ts).total_seconds() / 3600.0
    if elapsed_hours <= 0:
        return False

    if prev_lat is not None and prev_lon is not None and curr_lat is not None and curr_lon is not None:
        distance_km = _haversine_km(prev_lat, prev_lon, curr_lat, curr_lon)
        implied_speed_kmh = distance_km / elapsed_hours
        return implied_speed_kmh > MAX_PLAUSIBLE_TRAVEL_SPEED_KMH

    if prev_country and curr_country and prev_country != curr_country:
        return elapsed_hours < 1.0

    return False
