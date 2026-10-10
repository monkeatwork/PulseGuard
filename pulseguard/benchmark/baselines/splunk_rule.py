"""Splunk-style baseline (CLAUDE.md, evaluation rule #2): fires if a user
receives MORE THAN 9 MFA push prompts within any 10-minute sliding window.

This is the first yardstick every later detection stage is measured
against — it must be reproduced exactly, not approximated.
"""

from __future__ import annotations

from datetime import datetime

SPLUNK_PROMPT_THRESHOLD = 9
SPLUNK_WINDOW_SECONDS = 10 * 60


def evaluate_timestamps(prompt_timestamps: list[datetime]) -> bool:
    """True if any 10-minute window contains more than 9 prompts."""
    ts = sorted(prompt_timestamps)
    left = 0
    for right in range(len(ts)):
        while (ts[right] - ts[left]).total_seconds() > SPLUNK_WINDOW_SECONDS:
            left += 1
        if (right - left + 1) > SPLUNK_PROMPT_THRESHOLD:
            return True
    return False


def evaluate_burst(events: list[dict]) -> bool:
    """`events` is a burst's raw event records (dicts with `event_type`,
    `ts` keys), as produced by the benchmark generator."""
    prompt_timestamps = [e["ts"] for e in events if e["event_type"] == "mfa_prompt"]
    return evaluate_timestamps(prompt_timestamps)
