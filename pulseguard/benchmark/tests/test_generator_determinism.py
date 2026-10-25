"""Phase 1 gate: same seed -> byte-identical output.

Exercises benchmark.generator.cli.build_corpus/finalize_records directly
against a synthetic `users` dict, so this test does not depend on the
(large, network-fetched) RBA dataset being present.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pandas as pd

from benchmark.generator.cli import assign_profile, build_corpus, finalize_records

BASE_TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _fake_users(n: int = 30) -> dict[str, list[dict]]:
    users = {}
    for i in range(n):
        user_id = f"user{i}"
        users[user_id] = [
            {
                "event_id": None,
                "user_id": user_id,
                "ts": BASE_TS,
                "event_type": "login_attempt",
                "decision": None,
                "decision_latency_ms": None,
                "src_ip": f"10.0.0.{i}",
                "geo_country": "US",
                "device_id": f"device-{i}",
                "user_agent": "Mozilla/5.0 (fake)",
                "session_id": None,
                "ingest_ts": BASE_TS,
                "label_attack": False,
                "attack_profile": None,
                "burst_id": None,
            }
        ]
    return users


def _df_hash(df: pd.DataFrame) -> str:
    return hashlib.sha256(pd.util.hash_pandas_object(df, index=True).values.tobytes()).hexdigest()


def test_build_corpus_is_deterministic_given_same_seed():
    users_a = _fake_users()
    users_b = _fake_users()

    records_a, counts_a = build_corpus(42, users_a)
    records_b, counts_b = build_corpus(42, users_b)

    assert counts_a == counts_b

    df_a = finalize_records(records_a, seed=42)
    df_b = finalize_records(records_b, seed=42)

    assert _df_hash(df_a) == _df_hash(df_b)


def test_build_corpus_differs_with_different_seed():
    users_a = _fake_users()
    users_b = _fake_users()

    records_a, _ = build_corpus(1, users_a)
    records_b, _ = build_corpus(2, users_b)

    df_a = finalize_records(records_a, seed=1)
    df_b = finalize_records(records_b, seed=2)

    assert _df_hash(df_a) != _df_hash(df_b)


def test_profile_assignment_is_deterministic_and_order_independent():
    seed = 7
    user_ids = [f"user{i}" for i in range(200)]
    first_pass = {u: assign_profile(seed, u) for u in user_ids}
    second_pass = {u: assign_profile(seed, u) for u in reversed(user_ids)}
    assert first_pass == second_pass


def test_profile_mix_roughly_matches_configured_ratios():
    seed = 11
    user_ids = [f"user{i}" for i in range(5000)]
    from collections import Counter

    counts = Counter(assign_profile(seed, u) for u in user_ids)
    total = sum(counts.values())
    # 50% plain_benign is the largest single bucket by a wide margin
    assert counts["plain_benign"] / total > 0.4
    # every profile should appear at all at this sample size
    assert set(counts.keys()) == {
        "plain_benign",
        "benign_high_activity",
        "benign_occasional_denial",
        "high_volume_burst",
        "low_and_slow",
        "social_engineering_assisted",
    }


# --- Fatigue configuration ---------------------------------------------------

from benchmark.generator.latency_models import FatigueConfig  # noqa: E402

# _df_hash of the 300-user fake corpus at seed 42, computed with the generator
# as it was BEFORE fatigue strength became a parameter. If this moves, the
# default corpus moved, and every committed result is no longer reproducible.
GOLDEN_DEFAULT_CORPUS_HASH = "131aa35f4518c8424213256c0ad9e44fc6b730c9e1f69398eefb6ca59d5e0e34"


def _corpus(fatigue: FatigueConfig | None = None, n: int = 300) -> pd.DataFrame:
    kwargs = {} if fatigue is None else {"fatigue": fatigue}
    records, _ = build_corpus(42, _fake_users(n), **kwargs)
    return finalize_records(records, seed=42)


def test_default_fatigue_config_leaves_the_corpus_unchanged():
    assert _df_hash(_corpus()) == GOLDEN_DEFAULT_CORPUS_HASH
    assert _df_hash(_corpus(FatigueConfig())) == GOLDEN_DEFAULT_CORPUS_HASH


def test_fatigue_strength_changes_attack_latencies_only():
    """Paired corpora: the same users, episodes and decisions at every
    strength; only attack latencies (and the timestamps they push) move."""
    full = _corpus(FatigueConfig(strength=1.0, null_model="matched"))
    none = _corpus(FatigueConfig(strength=0.0, null_model="matched"))
    assert len(full) == len(none)
    assert full["burst_id"].equals(none["burst_id"])
    assert full["decision"].equals(none["decision"])
    benign = full["label_attack"] == False  # noqa: E712
    assert full.loc[benign, "decision_latency_ms"].equals(none.loc[benign, "decision_latency_ms"])
    attack = full["label_attack"] & full["decision_latency_ms"].notna()
    assert not full.loc[attack, "decision_latency_ms"].equals(none.loc[attack, "decision_latency_ms"])


def test_non_default_fatigue_config_is_still_deterministic():
    config = FatigueConfig(strength=0.5, shape="exponential", null_model="matched", heterogeneity=0.3)
    assert _df_hash(_corpus(config, 60)) == _df_hash(_corpus(config, 60))


def _max_benign_deny_run(df: pd.DataFrame) -> int:
    d = df[(df["event_type"] == "mfa_decision") & ~df["label_attack"].astype(bool)].sort_values(["burst_id", "ts"])
    best = 0
    for _, g in d.groupby("burst_id"):
        run = 0
        for decision in g["decision"]:
            run = run + 1 if decision == "deny" else 0
            best = max(best, run)
    return best


def test_benign_deny_runs_are_opt_in_and_leave_attacks_untouched():
    from benchmark.generator.attack_profiles import HardNegativeConfig

    base = _corpus()
    records, _ = build_corpus(42, _fake_users(300), FatigueConfig(), HardNegativeConfig(deny_run_rate=0.5))
    with_runs = finalize_records(records, seed=42)
    assert _max_benign_deny_run(base) <= 1  # the original corpus: never two in a row
    assert _max_benign_deny_run(with_runs) >= 2
    attack = lambda df: df[df["label_attack"].astype(bool)].drop(columns=["event_id"]).reset_index(drop=True)  # noqa: E731
    pd.testing.assert_frame_equal(attack(base), attack(with_runs))
    records, _ = build_corpus(42, _fake_users(300), FatigueConfig(), HardNegativeConfig(deny_run_rate=0.0))
    assert _df_hash(finalize_records(records, seed=42)) == GOLDEN_DEFAULT_CORPUS_HASH
