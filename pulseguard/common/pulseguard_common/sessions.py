"""Session-level aggregation: the unit PulseGuard scores, offline AND live.

Why this layer exists (REMEDIATION_TASK.md A1/A2, DECISIONS.md 2026-10-11
"Session-level scoring"): the 5-minute gap segmentation in windows.py is
deliberate -- it keeps a low-and-slow attack's 20-40 minute prompts from
looking like one dense burst -- but scoring each 5-minute fragment on its own
left every response-behaviour feature undefined for exactly the attack that
fixed-threshold SIEM rules miss, and made the live path score a different
object from the one the offline harness evaluated.

A *session* is a run of one user's MFA events where no two consecutive
events are more than SESSION_GAP_THRESHOLD_SECONDS apart. That threshold is
chosen to exceed the longest inter-prompt gap any modelled attack uses
(low-and-slow: 40 min), so one attack episode is one session, while a
genuinely new authentication episode (more than an hour of silence) starts
a fresh one. Inside a session, the fragment-level burst semantics are kept
intact: `prompts_per_window` still counts a 10-minute window, and
`windows.segment_into_bursts` still exists for anything that needs dense
bursts.

Scoring happens at every *decision point*: each time an `mfa_decision`
arrives, the session-so-far (every event up to and including that
decision) is featurised and scored. That is what the live feature engine
does on each decision event, and exactly what `feature_table.py` /
`sequence_dataset.py` replay offline -- so an episode's offline prediction
("did any decision point cross the threshold?") is the live alerting rule.

Everything here is pure: no Redis, no Kafka.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterator

from pulseguard_common.windows import PromptDecisionPair, pair_prompts_and_decisions

# Strictly greater than LOW_AND_SLOW_GAP_SECONDS_RANGE's upper bound (40 min)
# in benchmark/generator/attack_profiles.py. A test pins that relationship.
SESSION_GAP_THRESHOLD_SECONDS = 60 * 60

MFA_EVENT_TYPES = ("mfa_prompt", "mfa_decision")


def _ts(event: dict) -> datetime:
    return event["ts"]


def segment_events_into_sessions(
    events: list[dict], gap_threshold_seconds: float = SESSION_GAP_THRESHOLD_SECONDS
) -> list[list[dict]]:
    """Splits one user's MFA events into sessions. Input order does not
    matter (out-of-order arrival is handled by sorting on the IdP-issued
    `ts`, never `ingest_ts`); non-MFA events are ignored."""
    mfa = sorted((e for e in events if e.get("event_type") in MFA_EVENT_TYPES), key=_ts)
    if not mfa:
        return []
    sessions: list[list[dict]] = [[mfa[0]]]
    for prev, curr in zip(mfa, mfa[1:]):
        if (_ts(curr) - _ts(prev)).total_seconds() > gap_threshold_seconds:
            sessions.append([curr])
        else:
            sessions[-1].append(curr)
    return sessions


def session_pairs(session_events: list[dict]) -> list[PromptDecisionPair]:
    """Prompt/decision pairs for a whole session, with `prompt_index` set to
    the pair's position in the SESSION (not in its 5-minute fragment) -- the
    x-axis `latency_drift_slope` regresses over."""
    pairs = sorted(pair_prompts_and_decisions(sorted(session_events, key=_ts)), key=lambda p: p.prompt_ts)
    for i, pair in enumerate(pairs):
        pair.prompt_index = i
    return pairs


def decision_point_prefixes(session_events: list[dict]) -> Iterator[tuple[int, list[dict]]]:
    """Yields (decision_index, events_up_to_and_including_that_decision) for
    every `mfa_decision` in the session, in time order. `decision_index` is
    0-based. A session with prompts but no decision yields nothing: there is
    no user reaction to score yet."""
    ordered = sorted(session_events, key=_ts)
    decision_index = 0
    for i, event in enumerate(ordered):
        if event.get("event_type") == "mfa_decision":
            yield decision_index, ordered[: i + 1]
            decision_index += 1


def session_context(session_events: list[dict]) -> tuple[str | None, str]:
    """(country, device_id) for a session: taken from the session's own last
    event, never from another session or another burst in the same buffer
    (REMEDIATION_TASK.md C3)."""
    last = max(session_events, key=_ts)
    return last.get("geo_country"), last.get("device_id") or "unknown"


def episode_id(user_id: str, session_events: list[dict]) -> str:
    """Stable id for a live session: user plus the IdP timestamp of its
    first event. The same session always maps to the same id, so repeated
    decision-point scores update one alert instead of creating many."""
    first = min(session_events, key=_ts)
    return f"{user_id}:{_ts(first).isoformat()}"
