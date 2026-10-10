"""Per-burst enrichment orchestration: wires the pure feature functions
(windows/features_frequency/features_response) together with baseline state
(baseline_store/cohort_fallback) to produce one feature vector per finalized
burst. This is the actual L3 business logic; `streaming_app.py` is just
Kafka wiring around a call to `enrich_burst`.

Kept deliberately separate from Faust/Kafka so it is fully unit-testable
with a fake or real (Testcontainers) baseline store, without needing a
running stream (CLAUDE.md, "Feature computation is pure and
unit-testable in isolation from the stream").
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional, Protocol

from pulseguard_common import features_frequency as freq
from pulseguard_common import features_response as resp
from pulseguard_common.cohort_fallback import blend_baseline
from pulseguard_common.windows import PromptDecisionPair


class BaselineStoreProtocol(Protocol):
    def load_latency(self, user_id: str): ...
    def update_latency(self, user_id: str, latency_ms: float): ...
    def update_rate(self, user_id: str, inter_arrival_seconds: float): ...
    def is_country_known(self, user_id: str, country: str) -> bool: ...
    def record_country(self, user_id: str, country: str) -> None: ...
    def is_device_known(self, user_id: str, device_id: str) -> bool: ...
    def record_device(self, user_id: str, device_id: str) -> None: ...


@dataclass
class CohortBaselineProvider:
    """Resolves the cohort fallback baseline for a cold-start user. A
    concrete implementation looks this up from `pg:cohort:{cohort_id}:latency`
    (see redis_keys.py); tests can supply a trivial constant provider."""

    cohort_mean_ms: float = 5000.0  # a defensible global prior: matches the
    # generator's own benign approve-latency median (DECISIONS.md).
    cohort_std_ms: float = 3000.0  # the actual std of LogNormal(mu=1.6, sigma=0.5)
    # in ms (~2990ms, rounded) -- see DECISIONS.md, "Bug fix: cold-start
    # approval_latency_z used a 1ms std floor". Never use a floor on the
    # order of a few ms: that turns a "z-score" into the raw millisecond
    # deviation, which is enormous for any real latency and makes the
    # feature fire on every single approval regardless of actual anomaly.


@dataclass
class BurstFeatureVector:
    user_id: str
    n_prompts: int
    prompts_per_window: int
    inter_prompt_mean: Optional[float]
    inter_prompt_std: Optional[float]
    burst_duration_seconds: float
    off_hours_flag: bool
    geo_novelty: bool
    device_novelty: bool

    deny_run_length: int
    capitulation_flag: bool
    approval_latency_z: Optional[float]
    approval_latency_z_valid: bool
    latency_drift_slope: float
    latency_drift_slope_valid: bool
    post_burst_approval_gap_seconds: Optional[float]
    post_burst_approval_gap_valid: bool
    denial_latency_variance: float
    denial_latency_variance_valid: bool

    baseline_is_cold_start: bool

    def as_dict(self) -> dict:
        return asdict(self)


def compute_features(
    user_id: str,
    pairs: list[PromptDecisionPair],
    country: Optional[str],
    device_id: str,
    store: BaselineStoreProtocol,
    cohort_provider: CohortBaselineProvider,
    rolling_median_skew_seconds: float = 0.0,
) -> BurstFeatureVector:
    """Computes every feature for one burst or session prefix WITHOUT
    touching baseline state (reads only). Session-level scoring calls this
    once per decision point, so it must be side-effect free; baselines are
    advanced exactly once per closed session by `commit_baselines`."""
    prompt_timestamps = [p.prompt_ts for p in pairs]

    latency_baseline = store.load_latency(user_id)
    cold_start = latency_baseline.is_cold_start
    baseline_mean = blend_baseline(
        latency_baseline.mean_ms, cohort_provider.cohort_mean_ms, latency_baseline.event_count
    )
    baseline_std = (
        latency_baseline.std_ms
        if not cold_start
        else max(latency_baseline.std_ms, cohort_provider.cohort_std_ms)
    )

    drift = resp.compute_latency_drift_slope(pairs, rolling_median_skew_seconds)
    gap = resp.post_burst_approval_gap(pairs)
    variance = resp.denial_latency_variance(pairs)

    approve_pair = next((p for p in pairs if p.decision == "approve"), None)
    approve_latency = approve_pair.decision_latency_ms if approve_pair else None
    z = resp.approval_latency_z(approve_latency, baseline_mean, baseline_std)

    is_country_novel = bool(country) and not store.is_country_known(user_id, country)
    is_device_novel = not store.is_device_known(user_id, device_id)

    return BurstFeatureVector(
        user_id=user_id,
        n_prompts=len(pairs),
        prompts_per_window=freq.prompts_per_window(prompt_timestamps, prompt_timestamps[-1]),
        inter_prompt_mean=freq.inter_prompt_mean(prompt_timestamps),
        inter_prompt_std=freq.inter_prompt_std(prompt_timestamps),
        burst_duration_seconds=freq.burst_duration_seconds(prompt_timestamps),
        off_hours_flag=freq.off_hours_flag(prompt_timestamps[0]),
        geo_novelty=is_country_novel,
        device_novelty=is_device_novel,
        deny_run_length=resp.deny_run_length(pairs),
        capitulation_flag=resp.capitulation_flag(pairs),
        approval_latency_z=z.value,
        approval_latency_z_valid=z.valid,
        latency_drift_slope=drift.slope,
        latency_drift_slope_valid=drift.valid,
        post_burst_approval_gap_seconds=gap.seconds,
        post_burst_approval_gap_valid=gap.valid,
        denial_latency_variance=variance.value,
        denial_latency_variance_valid=variance.valid,
        baseline_is_cold_start=cold_start,
    )


def commit_baselines(
    user_id: str,
    pairs: list[PromptDecisionPair],
    country: Optional[str],
    device_id: str,
    store: BaselineStoreProtocol,
    all_approvals: bool = True,
) -> None:
    """Advances the user's baselines with a finished burst/session: approval
    latencies feed the EWMA latency baseline, and the session's country and
    device become "known". Called AFTER the unit has been scored, so a
    session is always scored against its own history, never itself."""
    approvals = [p.decision_latency_ms for p in pairs if p.decision == "approve" and p.decision_latency_ms is not None]
    if not all_approvals:
        approvals = approvals[:1]
    for latency in approvals:
        store.update_latency(user_id, float(latency))
    if country:
        store.record_country(user_id, country)
    store.record_device(user_id, device_id)


def enrich_burst(
    user_id: str,
    pairs: list[PromptDecisionPair],
    country: Optional[str],
    device_id: str,
    store: BaselineStoreProtocol,
    cohort_provider: CohortBaselineProvider,
    rolling_median_skew_seconds: float = 0.0,
) -> BurstFeatureVector:
    """compute_features + commit_baselines in one call (first approval only,
    the original per-burst semantics). Kept for single-shot callers and the
    existing unit tests; session scoring uses the two halves separately."""
    vector = compute_features(
        user_id, pairs, country, device_id, store, cohort_provider, rolling_median_skew_seconds
    )
    commit_baselines(user_id, pairs, country, device_id, store, all_approvals=False)
    return vector
