"""Metrics functions validated against hand-computed confusion matrices."""

from __future__ import annotations

import math

from eval.harness.metrics import breakdown_by_profile, compute_confusion


def test_confusion_matrix_matches_hand_computation():
    # 2 TP, 1 FP, 3 TN, 1 FN
    y_true = [True, True, False, False, False, False, True]
    y_pred = [True, True, True, False, False, False, False]
    confusion = compute_confusion(y_true, y_pred)
    assert confusion.tp == 2
    assert confusion.fp == 1
    assert confusion.tn == 3
    assert confusion.fn == 1


def test_precision_recall_fpr_hand_computed():
    y_true = [True, True, False, False, False, False, True]
    y_pred = [True, True, True, False, False, False, False]
    confusion = compute_confusion(y_true, y_pred)
    assert confusion.precision == 2 / 3
    assert confusion.recall == 2 / 3
    assert confusion.fpr == 1 / 4


def test_all_correct_gives_perfect_scores():
    y_true = [True, False, True, False]
    y_pred = [True, False, True, False]
    confusion = compute_confusion(y_true, y_pred)
    assert confusion.precision == 1.0
    assert confusion.recall == 1.0
    assert confusion.fpr == 0.0


def test_no_positive_predictions_gives_none_precision():
    y_true = [True, False]
    y_pred = [False, False]
    confusion = compute_confusion(y_true, y_pred)
    assert confusion.precision is None  # 0/0, not 0.0 — must not be silently wrong
    assert confusion.recall == 0.0
    assert confusion.fpr == 0.0


def test_no_negative_ground_truth_gives_none_fpr():
    y_true = [True, True]
    y_pred = [True, False]
    confusion = compute_confusion(y_true, y_pred)
    assert confusion.fpr is None  # no negatives to be falsely positive about


def test_breakdown_by_profile_separates_groups_correctly():
    rows = [
        {"attack_profile": "high_volume_burst", "y_true": True, "y_pred": True},
        {"attack_profile": "high_volume_burst", "y_true": True, "y_pred": False},
        {"attack_profile": "low_and_slow", "y_true": True, "y_pred": False},
        {"attack_profile": None, "y_true": False, "y_pred": True},
        {"attack_profile": None, "y_true": False, "y_pred": False},
    ]
    breakdown = breakdown_by_profile(rows)
    assert breakdown["high_volume_burst"]["tp"] == 1
    assert breakdown["high_volume_burst"]["fn"] == 1
    assert breakdown["low_and_slow"]["fn"] == 1
    assert breakdown["low_and_slow"]["recall"] == 0.0
    # None attack_profile (benign hard negative) grouped under the sentinel key
    assert breakdown["benign_high_activity"]["fp"] == 1
    assert breakdown["benign_high_activity"]["tn"] == 1
    assert breakdown["benign_high_activity"]["fpr"] == 0.5


def test_breakdown_by_profile_treats_float_nan_as_missing_not_a_real_profile():
    """Regression test: a parquet round-trip of an object column holding a
    mix of strings and None re-reads the None as float NaN, not Python
    None. NaN is truthy in Python, so a naive `profile or "sentinel"` check
    would create a bogus `nan`-keyed bucket instead of grouping these rows
    under "benign_high_activity" — this happened for real when training
    Stage B on the generated corpus."""
    rows = [
        {"attack_profile": float("nan"), "y_true": False, "y_pred": True},
        {"attack_profile": float("nan"), "y_true": False, "y_pred": False},
        {"attack_profile": "high_volume_burst", "y_true": True, "y_pred": True},
    ]
    breakdown = breakdown_by_profile(rows)
    assert "benign_high_activity" in breakdown
    assert not any(isinstance(k, float) and math.isnan(k) for k in breakdown)
    assert breakdown["benign_high_activity"]["fp"] == 1
    assert breakdown["benign_high_activity"]["tn"] == 1
