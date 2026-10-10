"""Cold-start cohort blending (DECISIONS.md, "Cohort fallback blending"):
`0.5*cohort + 0.5*user`, weighted by a `min(user_n/30, 1)` linear ramp — a
continuous transition from cohort-dominated to pure-user baseline, chosen
over a hard cutover to avoid a metric discontinuity at n=30.
"""

from __future__ import annotations

COLD_START_THRESHOLD_EVENTS = 30


def cohort_blend_ramp(user_event_count: int, threshold: int = COLD_START_THRESHOLD_EVENTS) -> float:
    if threshold <= 0:
        return 1.0
    return min(user_event_count / threshold, 1.0)


def blend_baseline(user_baseline: float, cohort_baseline: float, user_event_count: int) -> float:
    """At user_event_count=0: exactly the 50/50 blend. At
    user_event_count>=COLD_START_THRESHOLD_EVENTS: exactly the user's own
    baseline (cohort weight fully ramped to zero)."""
    ramp = cohort_blend_ramp(user_event_count)
    fifty_fifty = 0.5 * cohort_baseline + 0.5 * user_baseline
    return ramp * user_baseline + (1 - ramp) * fifty_fifty


def is_cold_start(user_event_count: int, threshold: int = COLD_START_THRESHOLD_EVENTS) -> bool:
    return user_event_count < threshold
