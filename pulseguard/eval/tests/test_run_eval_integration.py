"""Integration test: run both industry baselines end-to-end over a labelled
corpus shaped exactly like benchmark.generator.cli's output, through the
frozen harness (run_detector + split + metrics together).

Uses a small synthetic DataFrame rather than the full RBA-derived corpus so
this test runs anywhere without the ~1GB dataset — Phase 1's tests already
cover generator correctness against real data; this test covers the harness
plumbing (grouping, split filtering, confusion/breakdown wiring) end-to-end.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from eval.harness.run_eval import BASELINE_DETECTORS, run_detector
from eval.harness.split import assign_split

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
SEED = 42


def _burst_rows(user_id: str, burst_id: str, label_attack: bool, profile: str | None, pairs: list[tuple[float, str, float]]) -> list[dict]:
    """`pairs` = list of (prompt_offset_seconds, decision, latency_seconds)."""
    rows = []
    for offset, decision, latency in pairs:
        prompt_ts = T0 + timedelta(seconds=offset)
        decision_ts = prompt_ts + timedelta(seconds=latency)
        rows.append(
            dict(
                user_id=user_id, ts=prompt_ts, event_type="mfa_prompt", decision=None,
                label_attack=label_attack, attack_profile=profile, burst_id=burst_id,
            )
        )
        rows.append(
            dict(
                user_id=user_id, ts=decision_ts, event_type="mfa_decision", decision=decision,
                label_attack=label_attack, attack_profile=profile, burst_id=burst_id,
            )
        )
    return rows


def _build_synthetic_corpus() -> pd.DataFrame:
    rows = []
    # A high-volume attack burst: 12 prompts, 30s apart -> Splunk should fire.
    hv_pairs = [(i * 30, "deny" if i < 11 else "approve", 1.0) for i in range(12)]
    rows += _burst_rows("attacker_target_1", "burst_hv_1", True, "high_volume_burst", hv_pairs)

    # A low-and-slow attack burst: 8 prompts, 25 min apart -> Splunk should NOT fire
    # (this is precisely the gap PulseGuard exists to close).
    ls_pairs = [(i * 25 * 60, "deny" if i < 7 else "approve", 1.0) for i in range(8)]
    rows += _burst_rows("attacker_target_2", "burst_ls_1", True, "low_and_slow", ls_pairs)

    # A benign-high-activity hard negative: many approvals, no denials at all
    # -> neither baseline should ever fire.
    bh_pairs = [(i * 600, "approve", 2.0) for i in range(20)]
    rows += _burst_rows("poweruser_1", "burst_bh_1", False, None, bh_pairs)

    df = pd.DataFrame(rows)
    return df


@pytest.fixture(scope="module")
def corpus() -> pd.DataFrame:
    return _build_synthetic_corpus()


@pytest.fixture(scope="module")
def user_splits(corpus: pd.DataFrame) -> dict[str, str]:
    """The real split assignment for each synthetic user under SEED — used
    to build assertions from, rather than assuming any particular bucket."""
    return {u: assign_split(SEED, u) for u in corpus["user_id"].unique()}


def test_splunk_detects_high_volume_but_misses_low_and_slow(corpus):
    # split_filter=None: these assertions are about rule behaviour, not
    # split filtering (that is covered separately below and in
    # eval/tests/test_split_no_leakage.py).
    result = run_detector(corpus, BASELINE_DETECTORS["splunk"], SEED, split_filter=None)
    by_profile = result["by_profile"]
    assert by_profile["high_volume_burst"]["tp"] == 1
    assert by_profile["low_and_slow"]["fn"] == 1  # the documented detection gap
    assert by_profile["benign_high_activity"]["fp"] == 0


def test_elastic_detects_high_volume_but_misses_low_and_slow(corpus):
    result = run_detector(corpus, BASELINE_DETECTORS["elastic"], SEED, split_filter=None)
    by_profile = result["by_profile"]
    # elastic's window is also 10 minutes, so the low-and-slow burst (25 min
    # gaps) evades it too -- consecutive denials are always >10 min apart
    assert by_profile["high_volume_burst"]["tp"] == 1
    assert by_profile["low_and_slow"]["fn"] == 1
    assert by_profile["benign_high_activity"]["fp"] == 0


def test_run_detector_split_filter_includes_only_matching_users(corpus, user_splits):
    target_user = "attacker_target_1"
    own_split = user_splits[target_user]
    other_split = next(s for s in ("train", "val", "test") if s != own_split)

    included = run_detector(corpus, BASELINE_DETECTORS["splunk"], SEED, split_filter=own_split)
    excluded = run_detector(corpus, BASELINE_DETECTORS["splunk"], SEED, split_filter=other_split)

    included_profiles = set(included["by_profile"].keys())
    excluded_profiles = set(excluded["by_profile"].keys())
    assert "high_volume_burst" in included_profiles
    assert "high_volume_burst" not in excluded_profiles


def test_split_filter_none_evaluates_every_burst(corpus, user_splits):
    result = run_detector(corpus, BASELINE_DETECTORS["splunk"], SEED, split_filter=None)
    assert result["n_bursts_evaluated"] == 3

    per_split_total = sum(
        run_detector(corpus, BASELINE_DETECTORS["splunk"], SEED, split_filter=s)["n_bursts_evaluated"]
        for s in ("train", "val", "test")
    )
    assert per_split_total == 3


def test_overall_metrics_present_for_every_baseline(corpus):
    for name, detector in BASELINE_DETECTORS.items():
        result = run_detector(corpus, detector, SEED, split_filter=None)
        assert "precision" in result["overall"]
        assert "recall" in result["overall"]
        assert "fpr" in result["overall"]
        assert result["n_bursts_evaluated"] == 3
