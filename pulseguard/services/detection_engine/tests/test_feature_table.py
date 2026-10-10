"""Verifies build_feature_table correctly decomposes a low_and_slow
generator burst into many single-event gap-based bursts (each still
labelled attack via its parent burst_id), while a high_volume_burst stays
as one cohesive multi-event row — the exact distinction DECISIONS.md's
"Correction: Phase 4's planned low-and-slow recall target was wrong"
depends on.
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


def test_high_volume_burst_stays_as_one_cohesive_row():
    df = _build_corpus()
    table = build_feature_table(df)
    hv_rows = table[table["generator_burst_id"] == "gen_burst_hv"]
    assert len(hv_rows) == 1
    assert hv_rows.iloc[0]["n_prompts"] == 8
    assert hv_rows.iloc[0]["label_attack"] == True
    assert hv_rows.iloc[0]["deny_run_length"] == 7


def test_low_and_slow_fragments_into_single_event_rows_all_labelled_attack():
    df = _build_corpus()
    table = build_feature_table(df)
    ls_rows = table[table["generator_burst_id"] == "gen_burst_ls"]
    assert len(ls_rows) == 5  # fully fragmented, one row per prompt
    assert (ls_rows["n_prompts"] == 1).all()
    assert (ls_rows["label_attack"] == True).all()
    # each fragment individually has no burst-level signature to exploit
    assert (ls_rows["latency_drift_slope_valid"] == False).all()


def test_benign_high_activity_fragments_into_single_event_benign_rows():
    df = _build_corpus()
    table = build_feature_table(df)
    bh_rows = table[table["generator_burst_id"] == "gen_burst_bh"]
    assert len(bh_rows) == 4
    assert (bh_rows["n_prompts"] == 1).all()
    assert (bh_rows["label_attack"] == False).all()


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
