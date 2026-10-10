"""Hand-constructed boundary cases for the industry baseline rules
(CLAUDE.md, evaluation rule #2). These numbers are the yardstick for every
later phase, so the rules must be exactly right at the boundary, not
approximately right."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from benchmark.baselines.elastic_rule import evaluate_decisions
from benchmark.baselines.splunk_rule import evaluate_timestamps

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _ts_every(seconds: float, n: int) -> list[datetime]:
    return [T0 + timedelta(seconds=seconds * i) for i in range(n)]


def test_splunk_exactly_9_prompts_in_window_does_not_trigger():
    prompts = _ts_every(60, 9)  # 9 prompts, 8-minute span
    assert evaluate_timestamps(prompts) is False


def test_splunk_exactly_10_prompts_in_window_triggers():
    prompts = _ts_every(60, 10)  # 10 prompts, 9-minute span, all within 10 min
    assert evaluate_timestamps(prompts) is True


def test_splunk_10_prompts_spread_over_20_minutes_does_not_trigger():
    prompts = _ts_every(120, 10)  # 2-minute gaps, spans 18 minutes total
    assert evaluate_timestamps(prompts) is False


def test_splunk_empty_and_single_prompt_do_not_trigger():
    assert evaluate_timestamps([]) is False
    assert evaluate_timestamps([T0]) is False


def test_elastic_exactly_2_denials_then_success_triggers():
    decisions = [
        (T0, "deny"),
        (T0 + timedelta(minutes=1), "deny"),
        (T0 + timedelta(minutes=2), "approve"),
    ]
    assert evaluate_decisions(decisions) is True


def test_elastic_only_1_denial_then_success_does_not_trigger():
    decisions = [
        (T0, "deny"),
        (T0 + timedelta(minutes=1), "approve"),
    ]
    assert evaluate_decisions(decisions) is False


def test_elastic_2_denials_outside_window_then_success_does_not_trigger():
    decisions = [
        (T0, "deny"),
        (T0 + timedelta(minutes=1), "deny"),
        (T0 + timedelta(minutes=15), "approve"),  # 13+ min after the denials
    ]
    assert evaluate_decisions(decisions) is False


def test_elastic_denials_with_no_subsequent_approve_does_not_trigger():
    decisions = [(T0, "deny"), (T0 + timedelta(minutes=1), "deny")]
    assert evaluate_decisions(decisions) is False


def test_elastic_approve_with_no_prior_denials_does_not_trigger():
    assert evaluate_decisions([(T0, "approve")]) is False


def test_elastic_empty_does_not_trigger():
    assert evaluate_decisions([]) is False
