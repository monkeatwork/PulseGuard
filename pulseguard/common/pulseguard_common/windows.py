"""Burst segmentation and prompt/decision pairing.

Lives in pulseguard_common (not services/feature_engine) because both
feature_engine (to build bursts from raw events) and detection_engine (to
reconstruct sequences for Stage C from the enriched Kafka message) need it,
and each service's Docker image only copies its own service directory plus
common/ — a cross-service import would work in local pytest (whole repo on
sys.path) but silently break in the actual containerized deployment (see
DECISIONS.md's "cef_syslog.py moved" entry for the same pattern).

This is the feature engine's own inference of burst boundaries from a raw
chronological event stream — distinct from the benchmark generator's
ground-truth `burst_id` (which the detector must not see at inference time).
A burst is a run of `mfa_prompt` events where consecutive gaps stay under
`BURST_GAP_THRESHOLD_SECONDS` (DECISIONS.md, "Burst window and hop window
sizing").

Handles two of the four required `latency_drift_slope` edge cases at this
layer (CLAUDE.md, "Edge cases... in latency_drift_slope"):
  - out-of-order arrival: `segment_into_bursts` buffers within
    OUT_OF_ORDER_GRACE_SECONDS before finalizing a burst.
  - clock skew: exposed via `PromptDecisionPair.ingest_ts` so
    features_response.py can exclude skewed points from the regression.
The other two (single-event burst, missing latency) are handled in
features_response.py itself, since they only make sense at the point the
slope is actually computed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from pulseguard_common.time_utils import BURST_GAP_THRESHOLD_SECONDS, within_grace_window


@dataclass
class PromptDecisionPair:
    prompt_ts: datetime
    decision_ts: Optional[datetime]
    decision: Optional[str]  # "approve" | "deny" | "timeout" | None (never answered)
    decision_latency_ms: Optional[int]
    ingest_ts: Optional[datetime]  # of the decision event, for skew detection
    prompt_index: int  # position within its burst, assigned by segment_into_bursts


def pair_prompts_and_decisions(events: list[dict]) -> list[PromptDecisionPair]:
    """`events` must be chronologically sorted (by `ts`) mfa_prompt/mfa_decision
    records for a single user. A pending prompt with no decision before the
    next prompt arrives is treated as an unanswered/timeout prompt — this is
    a defensive fallback; the benchmark generator never produces overlapping
    challenges, but production streams are not guaranteed to be this clean.
    """
    pairs: list[PromptDecisionPair] = []
    pending_prompt_ts: Optional[datetime] = None

    for event in events:
        if event["event_type"] == "mfa_prompt":
            if pending_prompt_ts is not None:
                pairs.append(
                    PromptDecisionPair(
                        prompt_ts=pending_prompt_ts,
                        decision_ts=None,
                        decision=None,
                        decision_latency_ms=None,
                        ingest_ts=None,
                        prompt_index=-1,
                    )
                )
            pending_prompt_ts = event["ts"]
        elif event["event_type"] == "mfa_decision":
            pairs.append(
                PromptDecisionPair(
                    prompt_ts=pending_prompt_ts if pending_prompt_ts is not None else event["ts"],
                    decision_ts=event["ts"],
                    decision=event.get("decision"),
                    decision_latency_ms=event.get("decision_latency_ms"),
                    ingest_ts=event.get("ingest_ts"),
                    prompt_index=-1,
                )
            )
            pending_prompt_ts = None

    if pending_prompt_ts is not None:
        pairs.append(
            PromptDecisionPair(
                prompt_ts=pending_prompt_ts,
                decision_ts=None,
                decision=None,
                decision_latency_ms=None,
                ingest_ts=None,
                prompt_index=-1,
            )
        )

    return pairs


def segment_into_bursts(
    pairs: list[PromptDecisionPair],
    gap_threshold_seconds: float = BURST_GAP_THRESHOLD_SECONDS,
) -> list[list[PromptDecisionPair]]:
    """Groups chronologically sorted pairs into bursts by the gap between
    consecutive prompt timestamps. Assigns each pair's `prompt_index`
    (0-based, within its burst)."""
    if not pairs:
        return []

    ordered = sorted(pairs, key=lambda p: p.prompt_ts)
    bursts: list[list[PromptDecisionPair]] = [[ordered[0]]]

    for prev, curr in zip(ordered, ordered[1:]):
        gap = (curr.prompt_ts - prev.prompt_ts).total_seconds()
        if gap < gap_threshold_seconds:
            bursts[-1].append(curr)
        else:
            bursts.append([curr])

    for burst in bursts:
        for i, pair in enumerate(burst):
            pair.prompt_index = i

    return bursts


def is_burst_finalizable(burst: list[PromptDecisionPair], latest_known_ts: datetime) -> bool:
    """A burst should not be finalized (features emitted, alert raised) until
    the out-of-order grace window has elapsed past its last prompt — a
    late-arriving event within the grace window could still extend it."""
    last_ts = burst[-1].prompt_ts
    return not within_grace_window(latest_known_ts, last_ts)
