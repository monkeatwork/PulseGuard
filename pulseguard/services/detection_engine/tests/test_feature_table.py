"""Verifies build_feature_table's session-level, decision-point unit
(DECISIONS.md 2026-10-11, "Session-level scoring"): one row per decision,
each featurising the session-so-far. In particular a low_and_slow episode
paced 25 minutes apart is ONE session whose final row sees the whole deny
run and a valid latency_drift_slope (REMEDIATION_TASK.md A1 verification),
where the old per-fragment unit saw five isolated single prompts.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from services.detection_engine.app.feature_table import FEATURE_COLUMNS, build_feature_table, to_model_matrix

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _burst_rows(user_id, burst_id, label_attack, profile, pairs):
    rows = []
    for offset, decision, latency in pairs:
        prompt_ts = T0 + timedelta(seconds=offset)
        decision_ts = prompt_ts + timedelta(seconds=latency)
        rows.append(dict(user_id=user_id, ts=prompt_ts, event_type="mfa_prompt", decision=None,
                          decision_latency_ms=None, geo_country="US", device_id="d1",
                          label_attack=label_attack, attack_profile=profile, burst_id=burst_id))
        rows.append(dict(user_id=user_id, ts=decision_ts, event_type="mfa_decision", decision=decision,
                          decision_latency_ms=int(latency * 1000), geo_country="US", device_id="d1",
                          label_attack=label_attack, attack_profile=profile, burst_id=burst_id))
    return rows


def _build_corpus() -> pd.DataFrame:
    rows = []
    # high_volume_burst: 8 prompts, 30s apart -> ONE cohesive gap-burst
    hv_pairs = [(i * 30, "deny" if i < 7 else "approve", 1.0) for i in range(8)]
    rows += _burst_rows("attacker1", "gen_burst_hv", True, "high_volume_burst", hv_pairs)

    # low_and_slow: 5 prompts, 25 min apart -> FIVE separate single-event gap-bursts
    ls_pairs = [(i * 25 * 60, "deny" if i < 4 else "approve", 1.0) for i in range(5)]
    rows += _burst_rows("attacker2", "gen_burst_ls", True, "low_and_slow", ls_pairs)

    # benign_high_activity: 4 approvals, 20 min apart -> FOUR separate single-event gap-bursts
    bh_pairs = [(i * 20 * 60, "approve", 2.0) for i in range(4)]
    rows += _burst_rows("poweruser1", "gen_burst_bh", False, None, bh_pairs)

    return pd.DataFrame(rows)


def test_one_row_per_decision_point():
    table = build_feature_table(_build_corpus())
    counts = table.groupby("generator_burst_id").size().to_dict()
    assert counts == {"gen_burst_hv": 8, "gen_burst_ls": 5, "gen_burst_bh": 4}
    # each row sees the session so far: n_prompts grows 1, 2, 3, ...
    hv = table[table["generator_burst_id"] == "gen_burst_hv"].sort_values("decision_index")
    assert hv["n_prompts"].tolist() == list(range(1, 9))


def test_high_volume_burst_final_row_carries_the_whole_burst():
    table = build_feature_table(_build_corpus())
    hv_rows = table[table["generator_burst_id"] == "gen_burst_hv"]
    final = hv_rows.sort_values("decision_index").iloc[-1]
    assert final["n_prompts"] == 8
    assert final["label_attack"] == True
    assert final["deny_run_length"] == 7
    assert final["capitulation_flag"] == True


def test_low_and_slow_episode_is_one_session_with_valid_drift_slope():
    """A1 verification: the response-behaviour features are defined for
    low-and-slow, and deny_run_length reflects the whole episode."""
    table = build_feature_table(_build_corpus())
    ls_rows = table[table["generator_burst_id"] == "gen_burst_ls"].sort_values("decision_index")
    assert (ls_rows["session_index"] == 0).all()
    assert (ls_rows["label_attack"] == True).all()
    final = ls_rows.iloc[-1]
    assert final["n_prompts"] == 5
    assert final["deny_run_length"] == 4
    assert final["capitulation_flag"] == True
    assert final["latency_drift_slope_valid"] == True
    # the first decision point is a lone prompt: slope undefined there only
    assert ls_rows.iloc[0]["latency_drift_slope_valid"] == False


def test_benign_high_activity_rows_are_benign_and_stationary():
    table = build_feature_table(_build_corpus())
    bh_rows = table[table["generator_burst_id"] == "gen_burst_bh"].sort_values("decision_index")
    assert (bh_rows["label_attack"] == False).all()
    assert bh_rows.iloc[-1]["n_prompts"] == 4
    assert bh_rows.iloc[-1]["deny_run_length"] == 0
    assert bh_rows.iloc[-1]["latency_drift_slope"] == 0.0  # constant latency


def test_gap_longer_than_session_threshold_starts_a_new_session():
    from pulseguard_common.sessions import SESSION_GAP_THRESHOLD_SECONDS

    gap = SESSION_GAP_THRESHOLD_SECONDS + 60
    rows = _burst_rows("u9", "gen_two_sessions", False, None, [(0, "approve", 2.0), (gap, "approve", 2.0)])
    table = build_feature_table(pd.DataFrame(rows))
    assert table["session_index"].tolist() == [0, 1]
    assert table["n_prompts"].tolist() == [1, 1]


def test_to_model_matrix_has_no_missing_values():
    df = _build_corpus()
    table = build_feature_table(df)
    matrix = to_model_matrix(table)
    assert list(matrix.columns) == FEATURE_COLUMNS
    assert not matrix.isna().any().any()


def test_empty_input_returns_empty_table():
    df = pd.DataFrame(columns=["burst_id", "user_id", "ts", "event_type", "decision",
                                "decision_latency_ms", "geo_country", "device_id",
                                "label_attack", "attack_profile"])
    table = build_feature_table(df)
    assert table.empty


def test_vector_to_row_matches_to_model_matrix():
    from services.detection_engine.app.feature_table import vector_to_row

    table = build_feature_table(_build_corpus())
    matrix = to_model_matrix(table)
    for i, record in enumerate(table.to_dict("records")):
        assert list(vector_to_row(record)) == list(matrix.iloc[i].astype(float))
