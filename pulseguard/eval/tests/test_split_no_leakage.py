"""CLAUDE.md, evaluation rule #1: split by user, never by event. Zero
user_id overlap between splits, and the split must be stable across
repeated calls (no shuffle drift) — see DECISIONS.md, "Train/test split"."""

from __future__ import annotations

from eval.harness.split import assign_split, split_users, verify_no_leakage


def test_no_overlap_between_splits():
    user_ids = [f"user{i}" for i in range(10_000)]
    split_map = split_users(42, user_ids)
    verify_no_leakage(split_map)  # raises on any overlap


def test_split_is_stable_across_repeated_calls():
    user_ids = [f"user{i}" for i in range(1000)]
    first = split_users(42, user_ids)
    second = split_users(42, user_ids)
    assert first == second


def test_split_is_stable_regardless_of_input_order():
    user_ids = [f"user{i}" for i in range(1000)]
    forward = {u: assign_split(42, u) for u in user_ids}
    backward = {u: assign_split(42, u) for u in reversed(user_ids)}
    assert forward == backward


def test_split_proportions_approximate_70_15_15():
    user_ids = [f"user{i}" for i in range(20_000)]
    split_map = split_users(42, user_ids)
    total = len(user_ids)
    train_pct = len(split_map["train"]) / total
    val_pct = len(split_map["val"]) / total
    test_pct = len(split_map["test"]) / total
    assert 0.65 < train_pct < 0.75
    assert 0.10 < val_pct < 0.20
    assert 0.10 < test_pct < 0.20


def test_different_seed_produces_different_split():
    user_ids = [f"user{i}" for i in range(1000)]
    split_a = {u: assign_split(1, u) for u in user_ids}
    split_b = {u: assign_split(2, u) for u in user_ids}
    assert split_a != split_b


def test_every_user_assigned_exactly_one_split():
    user_ids = [f"user{i}" for i in range(500)]
    split_map = split_users(42, user_ids)
    all_assigned = split_map["train"] + split_map["val"] + split_map["test"]
    assert sorted(all_assigned) == sorted(user_ids)
