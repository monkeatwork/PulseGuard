"""Unit tests for the research experiments (eval/research). Pure: no RBA
dataset, no model training."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from benchmark.baselines import elastic_rule, splunk_rule
from benchmark.generator.latency_models import DEFAULT_FATIGUE
from eval.research.adaptive_attacker import _next_usual_time, generate_adaptive_attack
from eval.research.before_capitulation import _detector_stats, episode_timeline, first_rule_firing
from eval.research.stats import across_seeds, wilson

T0 = datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc)


def _pair(i: int, decision: str, gap_s: int = 30) -> list[dict]:
    ts = T0 + timedelta(seconds=i * gap_s)
    return [
        {"event_type": "mfa_prompt", "ts": ts, "decision": None},
        {"event_type": "mfa_decision", "ts": ts + timedelta(seconds=2), "decision": decision},
    ]


def _episode(decisions: list[str], gap_s: int = 30) -> list[dict]:
    return [e for i, d in enumerate(decisions) for e in _pair(i, d, gap_s)]


def test_timeline_finds_the_first_approval():
    events = _episode(["deny", "deny", "approve"])
    tl = episode_timeline(events)
    assert tl["decision_event_index"] == [1, 3, 5]
    assert tl["capitulation_index"] == 5


def test_timeline_without_approval_has_no_capitulation():
    assert episode_timeline(_episode(["deny"] * 4))["capitulation_index"] is None


def test_elastic_can_only_fire_on_the_approval_itself():
    events = _episode(["deny", "deny", "deny", "approve"])
    assert first_rule_firing(events, elastic_rule.evaluate_burst) == episode_timeline(events)["capitulation_index"]


def test_splunk_fires_on_the_tenth_prompt_in_ten_minutes():
    events = _episode(["deny"] * 11 + ["approve"])
    idx = first_rule_firing(events, splunk_rule.evaluate_burst)
    assert events[idx]["event_type"] == "mfa_prompt"
    assert sum(1 for e in events[: idx + 1] if e["event_type"] == "mfa_prompt") == 10


def _row(capitulation, fired, counts):
    return {"attack_profile": "x", "capitulation_index": capitulation, "prompts_at_capitulation": (
        counts[capitulation] if capitulation is not None else None), "prompt_counts": counts, "det": fired}


def test_before_capitulation_counts_only_strictly_earlier_firings():
    counts = [1, 1, 2, 2, 3, 3]
    rows = [
        _row(5, 3, counts),  # fired on the 2nd decision, before the approval
        _row(5, 5, counts),  # fired on the approval itself: too late
        _row(5, None, counts),  # never fired
        _row(None, 1, counts),  # victim held out; detected anyway
    ]
    stats = _detector_stats(rows, "det")
    assert stats["n_capitulated"] == 3
    assert stats["detected_before_capitulation"] == pytest.approx(1 / 3)
    assert stats["detected_only_at_or_after_capitulation"] == pytest.approx(1 / 3)
    assert stats["missed_capitulated"] == pytest.approx(1 / 3)
    assert stats["median_prompts_to_spare"] == 1  # 3 prompts at capitulation - 2 at detection
    assert stats["detected_when_victim_held_out"] == 1.0


def test_next_usual_time_moves_into_a_usual_hour():
    rng = np.random.default_rng(0)
    moved = _next_usual_time(T0.replace(hour=3), [14], rng)
    assert moved.hour == 14 and moved > T0.replace(hour=3)
    assert _next_usual_time(T0, [9], rng) == T0  # already usual: unchanged


VICTIM = {"src_ip": "10.0.0.1", "device_id": "d", "user_agent": "ua", "country": "US"}


@pytest.mark.parametrize("gap", [60, 3600, 14400])
def test_adaptive_attack_respects_pacing(gap):
    events = generate_adaptive_attack(np.random.default_rng(1), "u", T0, VICTIM, gap, None, False, DEFAULT_FATIGUE)
    prompts = [e.ts for e in events if e.event_type == "mfa_prompt"]
    gaps = [(b - a).total_seconds() for a, b in zip(prompts, prompts[1:])]
    assert all(0.8 * gap <= g <= 1.2 * gap + 60 for g in gaps)


def test_adaptive_attack_with_usual_hours_only_prompts_in_those_hours():
    events = generate_adaptive_attack(np.random.default_rng(2), "u", T0, VICTIM, 600, [9, 10], False, DEFAULT_FATIGUE)
    assert all(e.ts.hour in (9, 10) for e in events if e.event_type == "mfa_prompt")


def test_adaptive_attack_with_lure_ends_on_an_approval_after_a_denial():
    events = generate_adaptive_attack(np.random.default_rng(3), "u", T0, VICTIM, 60, None, True, DEFAULT_FATIGUE)
    decisions = [e.decision for e in events if e.event_type == "mfa_decision"]
    assert decisions[-1] == "approve" and decisions[0] == "deny"
    assert decisions.count("approve") == 1


def test_wilson_interval_contains_the_estimate_and_stays_in_unit_range():
    lo, hi = wilson(0, 50)
    assert lo == pytest.approx(0.0, abs=1e-12) and 0 < hi < 0.1
    lo, hi = wilson(30, 40)
    assert lo < 0.75 < hi
    assert wilson(0, 0) == (None, None)


def test_across_seeds_interval_is_clipped_to_rates():
    s = across_seeds([1.0, 0.98, 1.0])
    assert s["n_seeds"] == 3 and s["ci_high"] <= 1.0 and s["ci_low"] < s["mean"]
    assert across_seeds([None])["mean"] is None


def test_deny_run_rule_needs_two_consecutive_denials():
    from eval.research.suite import deny_run_rule

    assert deny_run_rule(_episode(["deny", "deny", "approve"]))
    assert not deny_run_rule(_episode(["deny", "approve", "deny", "approve"]))
    assert not deny_run_rule(_episode(["approve"] * 5))
