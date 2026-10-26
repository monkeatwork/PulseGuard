"""Cross-session unresolved-denial counter.

Session-level scoring forgets everything at a 60-minute gap, so an attacker
who paces prompts further apart than that never builds a burst
(eval/results/adaptive_attacker.json: PulseGuard recall 0 at 2-4 h gaps).
This guard remembers, per user and across sessions, denials that were never
followed by an approval, and fires once `min_denials` of them fall inside a
trailing window.

Only UNRESOLVED denials count. A legitimate user who denies a prompt (a
mis-tap, a login they did not recognise at first) usually approves a retry
within minutes; a prompt nobody on the user's side asked for is denied and
left alone. Counting raw denials instead flags 6.5% of benign episodes at
4 denials / 24 h on the default corpus (DECISIONS.md, 2026-10-26
"Cross-session guard"). A denial becomes unresolved once `resolve_seconds`
pass with no approval from that user, so the guard never sees a denial as
unresolved before then.

Pure: state is passed in and mutated, no I/O.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CrossSessionGuardConfig:
    min_denials: int = 3
    window_seconds: int = 24 * 3600
    resolve_seconds: int = 10 * 60

    def as_dict(self) -> dict:
        return {
            "min_denials": self.min_denials,
            "window_seconds": self.window_seconds,
            "resolve_seconds": self.resolve_seconds,
        }


DEFAULT_GUARD = CrossSessionGuardConfig()


@dataclass
class DenialHistory:
    """One user's recent decisions, kept sorted (out-of-order arrival is
    inserted at its timestamp) and pruned to what the window can still use."""

    denials: list[datetime] = field(default_factory=list)
    approvals: list[datetime] = field(default_factory=list)


def _resolved(history: DenialHistory, denial: datetime, resolve: timedelta) -> bool:
    i = bisect.bisect_right(history.approvals, denial)
    return i < len(history.approvals) and history.approvals[i] - denial <= resolve


def unresolved_denials(history: DenialHistory, ts: datetime, config: CrossSessionGuardConfig = DEFAULT_GUARD) -> int:
    """Denials in [ts - window, ts - resolve] with no approval within
    `resolve` after them."""
    window, resolve = timedelta(seconds=config.window_seconds), timedelta(seconds=config.resolve_seconds)
    lo = bisect.bisect_left(history.denials, ts - window)
    hi = bisect.bisect_right(history.denials, ts - resolve)
    return sum(not _resolved(history, d, resolve) for d in history.denials[lo:hi])


def observe(history: DenialHistory, ts: datetime, decision: str, config: CrossSessionGuardConfig = DEFAULT_GUARD) -> bool:
    """Records one MFA decision; True if the user has `min_denials`
    unresolved denials in the window ending at `ts`."""
    bisect.insort(history.denials if decision == "deny" else history.approvals, ts)
    horizon = max(history.denials[-1:] + history.approvals[-1:]) - timedelta(
        seconds=config.window_seconds + config.resolve_seconds
    )
    for times in (history.denials, history.approvals):
        del times[: bisect.bisect_left(times, horizon)]
    return unresolved_denials(history, ts, config) >= config.min_denials


def unresolved_counts(events_df: pd.DataFrame, config: CrossSessionGuardConfig = DEFAULT_GUARD) -> pd.Series:
    """Batch form of `observe` for evaluation: for every mfa_decision row,
    that user's unresolved-denial count at the row's timestamp. Indexed like
    the decision rows of `events_df`."""
    dec = events_df[events_df["event_type"] == "mfa_decision"][["user_id", "ts", "decision"]]
    out = pd.Series(0, index=dec.index, dtype=int)
    window = np.timedelta64(config.window_seconds, "s")
    resolve = np.timedelta64(config.resolve_seconds, "s")
    for _, g in dec.groupby("user_id", sort=False):
        ts = pd.to_datetime(g["ts"], utc=True).dt.tz_localize(None).to_numpy(dtype="datetime64[ns]")
        is_deny = (g["decision"] == "deny").to_numpy()
        denials, approvals = np.sort(ts[is_deny]), np.sort(ts[~is_deny])
        if len(denials) == 0:
            continue
        nxt = np.searchsorted(approvals, denials, side="right")
        has_next = nxt < len(approvals)
        resolved = np.zeros(len(denials), dtype=bool)
        resolved[has_next] = approvals[nxt[has_next]] - denials[has_next] <= resolve
        unresolved = denials[~resolved]
        hi = np.searchsorted(unresolved, ts - resolve, side="right")
        lo = np.searchsorted(unresolved, ts - window, side="left")
        out.loc[g.index] = np.maximum(hi - lo, 0)
    return out
