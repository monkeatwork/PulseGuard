from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from services.detection_engine.app.cross_session_guard import (
    CrossSessionGuardConfig,
    DenialHistory,
    observe,
    unresolved_counts,
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
CFG = CrossSessionGuardConfig(min_denials=3, window_seconds=24 * 3600, resolve_seconds=600)


def _feed(decisions, config=CFG):
    history = DenialHistory()
    return [observe(history, T0 + timedelta(hours=h), d, config) for h, d in decisions]


def test_three_unresolved_denials_hours_apart_fire_across_sessions():
    # 2 h apart: every prompt is its own session, which is what session scoring misses
    fired = _feed([(0, "deny"), (2, "deny"), (4, "deny"), (6, "approve")])
    assert fired == [False, False, False, True]


def test_denials_followed_by_an_approval_within_the_resolve_window_do_not_count():
    # deny, retry approved 5 min later, three times over
    decisions = []
    for h in (0, 2, 4):
        decisions += [(h, "deny"), (h + 5 / 60, "approve")]
    assert not any(_feed(decisions + [(6, "deny"), (6.5, "approve")]))


def test_a_denial_is_not_unresolved_before_the_resolve_window_has_passed():
    fired = _feed([(0, "deny"), (1, "deny"), (2, "deny"), (2 + 5 / 60, "deny")])
    # at h=2 + 5 min the third denial is only 5 min old: still pending
    assert fired == [False, False, False, False]


def test_denials_older_than_the_window_drop_out():
    fired = _feed([(0, "deny"), (12, "deny"), (30, "deny"), (31, "deny")])
    assert fired == [False, False, False, False]


def test_out_of_order_arrival_gives_the_same_answer():
    in_order = [(0, "deny"), (2, "deny"), (4, "deny"), (6, "approve")]
    shuffled = [(2, "deny"), (0, "deny"), (4, "deny"), (6, "approve")]
    assert _feed(in_order)[-1] == _feed(shuffled)[-1] is True


def test_batch_counts_match_the_streaming_guard():
    rng = np.random.default_rng(7)
    rows = []
    for user in ("u1", "u2", "u3"):
        ts = T0
        for _ in range(60):
            ts += timedelta(minutes=int(rng.integers(1, 600)))
            rows.append({"user_id": user, "ts": ts, "event_type": "mfa_decision",
                         "decision": "deny" if rng.random() < 0.5 else "approve"})
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    counts = unresolved_counts(df, CFG)
    for user, g in df.groupby("user_id"):
        history = DenialHistory()
        streamed = [observe(history, t.to_pydatetime(), d, CFG) for t, d in zip(g["ts"], g["decision"])]
        assert streamed == (counts.loc[g.index] >= CFG.min_denials).tolist(), user
