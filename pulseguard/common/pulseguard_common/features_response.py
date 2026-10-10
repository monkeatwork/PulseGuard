"""Response-behaviour features — the project's contribution (CLAUDE.md,
"The core insight"). All functions are pure, taking a burst's
`PromptDecisionPair` list plus already-resolved baseline values.

`latency_drift_slope` is "the single most important feature in the system"
(CLAUDE.md) and is the only feature with explicitly mandated edge-case
handling, all implemented here:
  - single-event burst -> slope=0.0, valid=False
  - missing latency values -> excluded from the regression fit
  - clock skew -> events whose ingest/issue gap deviates from the user's
    rolling median skew are excluded from the regression fit
  - out-of-order arrival -> handled upstream in windows.py (grace window);
    this module just needs prompt_index to already reflect chronological
    order, which segment_into_bursts guarantees
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import pvariance
from typing import Optional

from pulseguard_common.time_utils import is_clock_skewed
from pulseguard_common.windows import PromptDecisionPair

# A burst needs a deny run of at least this length before an approval counts
# as "capitulation" rather than an isolated, possibly-honest mis-tap. Chosen
# to match Elastic's own 2-denial threshold (DECISIONS.md).
MIN_DENIALS_FOR_CAPITULATION = 2


def deny_run_length(pairs: list[PromptDecisionPair]) -> int:
    """Consecutive denials before the first approval (0 if the burst never
    contains a leading deny run, e.g. it starts with an approve)."""
    count = 0
    for pair in pairs:
        if pair.decision == "deny":
            count += 1
        else:
            break
    return count


def capitulation_flag(pairs: list[PromptDecisionPair]) -> bool:
    """The deny -> deny -> ... -> approve signature: a leading run of at
    least MIN_DENIALS_FOR_CAPITULATION denials immediately followed by an
    approval."""
    run = deny_run_length(pairs)
    if run < MIN_DENIALS_FOR_CAPITULATION or run >= len(pairs):
        return False
    return pairs[run].decision == "approve"


@dataclass(frozen=True)
class ApprovalLatencyZ:
    value: Optional[float]
    valid: bool


def approval_latency_z(
    latency_ms: Optional[float],
    baseline_mean_ms: float,
    baseline_std_ms: float,
) -> ApprovalLatencyZ:
    """z-score of an approval's latency against the user's own historical
    distribution. Invalid (rather than a fabricated 0.0) when there is no
    latency to score or the baseline has no meaningful spread yet (early
    cold-start, before enough events establish a non-zero variance)."""
    if latency_ms is None:
        return ApprovalLatencyZ(value=None, valid=False)
    if baseline_std_ms <= 0:
        return ApprovalLatencyZ(value=None, valid=False)
    return ApprovalLatencyZ(value=(latency_ms - baseline_mean_ms) / baseline_std_ms, valid=True)


@dataclass(frozen=True)
class LatencyDriftResult:
    slope: float
    valid: bool
    n_points_used: int
    timeout_count: int
    skew_excluded_count: int


def compute_latency_drift_slope(
    pairs: list[PromptDecisionPair],
    rolling_median_skew_seconds: float = 0.0,
) -> LatencyDriftResult:
    """Linear regression slope of decision latency (ms) against prompt_index
    within one burst. See module docstring for the four mandated edge cases.
    """
    timeout_count = sum(1 for p in pairs if p.decision_latency_ms is None)

    # Edge case: single-event burst.
    if len(pairs) <= 1:
        return LatencyDriftResult(
            slope=0.0, valid=False, n_points_used=len(pairs),
            timeout_count=timeout_count, skew_excluded_count=0,
        )

    skew_excluded_count = 0
    xs: list[float] = []
    ys: list[float] = []
    for pair in pairs:
        # Edge case: missing latency values excluded from the fit.
        if pair.decision_latency_ms is None:
            continue
        # Edge case: clock skew excluded from the fit.
        if pair.ingest_ts is not None and pair.decision_ts is not None:
            if is_clock_skewed(pair.decision_ts, pair.ingest_ts, rolling_median_skew_seconds):
                skew_excluded_count += 1
                continue
        xs.append(float(pair.prompt_index))
        ys.append(float(pair.decision_latency_ms))

    # Edge case: all latencies missing/excluded -> nothing to regress.
    if len(xs) < 2:
        return LatencyDriftResult(
            slope=0.0, valid=False, n_points_used=len(xs),
            timeout_count=timeout_count, skew_excluded_count=skew_excluded_count,
        )

    n = len(xs)
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    denominator = sum((x - x_mean) ** 2 for x in xs)

    if denominator == 0:
        # All remaining points share the same prompt_index (degenerate after
        # exclusions) -- no slope is computable.
        return LatencyDriftResult(
            slope=0.0, valid=False, n_points_used=n,
            timeout_count=timeout_count, skew_excluded_count=skew_excluded_count,
        )

    slope = numerator / denominator
    return LatencyDriftResult(
        slope=slope, valid=True, n_points_used=n,
        timeout_count=timeout_count, skew_excluded_count=skew_excluded_count,
    )


@dataclass(frozen=True)
class PostBurstApprovalGap:
    seconds: Optional[float]
    valid: bool


def post_burst_approval_gap(pairs: list[PromptDecisionPair]) -> PostBurstApprovalGap:
    """Interval between the final denial and the eventual approval. Invalid
    when the burst has no denial before its approval (e.g. immediate
    approval, or the burst never resolves to an approval at all)."""
    approve_idx = next((i for i, p in enumerate(pairs) if p.decision == "approve"), None)
    if approve_idx is None:
        return PostBurstApprovalGap(seconds=None, valid=False)

    deny_indices = [i for i in range(approve_idx) if pairs[i].decision == "deny"]
    if not deny_indices:
        return PostBurstApprovalGap(seconds=None, valid=False)

    last_deny = pairs[deny_indices[-1]]
    approve = pairs[approve_idx]
    if last_deny.decision_ts is None or approve.decision_ts is None:
        return PostBurstApprovalGap(seconds=None, valid=False)

    gap = (approve.decision_ts - last_deny.decision_ts).total_seconds()
    return PostBurstApprovalGap(seconds=gap, valid=True)


@dataclass(frozen=True)
class DenialLatencyVariance:
    value: float
    valid: bool


def denial_latency_variance(pairs: list[PromptDecisionPair]) -> DenialLatencyVariance:
    """Spread of denial response times within the burst. Invalid (not a
    fabricated 0.0) with fewer than 2 denials to measure spread over."""
    latencies = [
        float(p.decision_latency_ms)
        for p in pairs
        if p.decision == "deny" and p.decision_latency_ms is not None
    ]
    if len(latencies) < 2:
        return DenialLatencyVariance(value=0.0, valid=False)
    return DenialLatencyVariance(value=pvariance(latencies), valid=True)
