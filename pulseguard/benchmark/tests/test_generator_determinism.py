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
