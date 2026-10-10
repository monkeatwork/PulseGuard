from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from services.detection_engine.app.sequence_dataset import (
    SEQUENCE_LENGTH,
    STEP_FEATURE_DIM,
    build_sequence_dataset,
    pairs_to_sequence,
)
from pulseguard_common.windows import pair_prompts_and_decisions

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


def test_pairs_to_sequence_shape_and_padding():
    events = _burst_rows("u1", "b1", True, "high_volume_burst", [(0, "deny", 1.0), (30, "approve", 0.5)])
    pairs = pair_prompts_and_decisions(events)
    seq, length = pairs_to_sequence(pairs)
    assert seq.shape == (SEQUENCE_LENGTH, STEP_FEATURE_DIM)
    assert length == 2
    # padded region (steps 2..19) is all zero
    assert np.all(seq[2:] == 0.0)


def test_pairs_to_sequence_truncates_to_last_n_when_longer():
    pairs_input = [(i * 30, "deny" if i < 24 else "approve", 1.0) for i in range(25)]
    events = _burst_rows("u1", "b1", True, "high_volume_burst", pairs_input)
    pairs = pair_prompts_and_decisions(events)
    seq, length = pairs_to_sequence(pairs)
    assert length == SEQUENCE_LENGTH
    # last step should reflect the FINAL (approve) decision, not an early one
    is_approve_col = 1
    assert seq[-1][is_approve_col] == 1.0


def test_pairs_to_sequence_single_event_has_length_one():
    events = _burst_rows("u1", "b1", False, None, [(0, "approve", 2.0)])
    pairs = pair_prompts_and_decisions(events)
    seq, length = pairs_to_sequence(pairs)
    assert length == 1


def test_build_sequence_dataset_shapes_and_labels():
    rows = []
    rows += _burst_rows("attacker1", "burst_hv", True, "high_volume_burst",
                         [(i * 30, "deny" if i < 4 else "approve", 1.0) for i in range(5)])
    rows += _burst_rows("poweruser1", "burst_bh", False, None, [(0, "approve", 2.0)])
    df = pd.DataFrame(rows)

    X, lengths, y, user_ids, profiles, burst_ids = build_sequence_dataset(df)
    assert X.shape == (2, SEQUENCE_LENGTH, STEP_FEATURE_DIM)
    assert lengths.shape == (2,)
    assert y.shape == (2,)
    assert set(y.tolist()) == {True, False}
    assert set(user_ids) == {"attacker1", "poweruser1"}
    assert set(burst_ids) == {"burst_hv", "burst_bh"}


def test_build_sequence_dataset_empty_input():
    df = pd.DataFrame(columns=["burst_id", "user_id", "ts", "event_type", "decision",
                                "decision_latency_ms", "geo_country", "device_id",
                                "label_attack", "attack_profile"])
    X, lengths, y, user_ids, profiles, burst_ids = build_sequence_dataset(df)
    assert X.shape == (0, SEQUENCE_LENGTH, STEP_FEATURE_DIM)
    assert len(user_ids) == 0
    assert len(burst_ids) == 0
