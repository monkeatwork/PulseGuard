"""Elastic-style baseline (CLAUDE.md, evaluation rule #2): fires if a user
has at least 2 denials followed by a successful approval, all within a
10-minute window.
"""

from __future__ import annotations

from datetime import datetime, timedelta

ELASTIC_DENIAL_THRESHOLD = 2
ELASTIC_WINDOW_SECONDS = 10 * 60


def evaluate_decisions(decisions: list[tuple[datetime, str]]) -> bool:
    """`decisions` is a list of (ts, decision) pairs, decision in
    {"approve", "deny", "timeout"}. True if some approve is preceded, within
    the prior 10 minutes, by at least 2 denials."""
    ordered = sorted(decisions, key=lambda d: d[0])
    for i, (ts, decision) in enumerate(ordered):
        if decision != "approve":
            continue
        window_start = ts - timedelta(seconds=ELASTIC_WINDOW_SECONDS)
        denial_count = sum(
            1 for prior_ts, prior_decision in ordered[:i]
            if prior_decision == "deny" and prior_ts >= window_start
        )
        if denial_count >= ELASTIC_DENIAL_THRESHOLD:
            return True
    return False


def evaluate_burst(events: list[dict]) -> bool:
    decisions = [
        (e["ts"], e["decision"]) for e in events if e["event_type"] == "mfa_decision"
    ]
    return evaluate_decisions(decisions)
