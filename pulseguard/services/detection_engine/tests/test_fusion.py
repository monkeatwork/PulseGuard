from __future__ import annotations

import pandas as pd
import pytest

from services.detection_engine.app.fusion import (
    FusionWeights,
    aggregate_fragment_scores_to_episode,
    fuse_scores,
    normalize_stage_a_score,
)


def test_default_weights_sum_to_one():
    w = FusionWeights().normalized()
    assert w.weight_a + w.weight_b + w.weight_c == pytest.approx(1.0)


def test_default_weights_favor_stage_b():
    w = FusionWeights()
    assert w.weight_b > w.weight_a
    assert w.weight_b > w.weight_c


def test_normalize_stage_a_score_caps_at_one():
    assert normalize_stage_a_score(0.0) == 0.0
    assert normalize_stage_a_score(2.5) == 0.5
    assert normalize_stage_a_score(100.0) == 1.0
    assert normalize_stage_a_score(-5.0) == 0.0


def test_fuse_scores_all_zero_is_zero():
    assert fuse_scores(0.0, 0.0, 0.0) == 0.0


def test_fuse_scores_all_max_is_one():
    assert fuse_scores(100.0, 1.0, 1.0) == pytest.approx(1.0)


def test_fuse_scores_weighted_combination():
    # a=0 (normalized 0), b=1.0, c=0.0 -> weight_b contribution only
    weights = FusionWeights(weight_a=0.25, weight_b=0.45, weight_c=0.30)
    score = fuse_scores(0.0, 1.0, 0.0, weights)
    assert score == pytest.approx(0.45)


def test_fuse_scores_custom_weights_are_normalized():
    # weights that don't sum to 1 (e.g. 2, 2, 2 -> each normalizes to 1/3)
    weights = FusionWeights(weight_a=2.0, weight_b=2.0, weight_c=2.0)
    score = fuse_scores(100.0, 1.0, 1.0, weights)  # a normalizes to 1.0 too
    assert score == pytest.approx(1.0)


def test_aggregate_fragment_scores_to_episode_uses_max():
    df = pd.DataFrame(
        {
            "episode": ["e1", "e1", "e1", "e2"],
            "score": [0.1, 0.9, 0.3, 0.5],
        }
    )
    result = aggregate_fragment_scores_to_episode(df, "episode", "score")
    assert result["e1"] == pytest.approx(0.9)
    assert result["e2"] == pytest.approx(0.5)
