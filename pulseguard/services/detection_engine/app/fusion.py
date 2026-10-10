"""Combines Stage A, Stage B, and Stage C scores into one fused score per
user-episode (CLAUDE.md, L4 architecture: "Weighted fusion"). Initial
weights per DECISIONS.md, "Fusion weights and threshold placement":
0.25*A + 0.45*B + 0.30*C, retuned only via a documented grid search over
the validation split (tune_fusion_weights.py) — never silently, never
touching the test split.

Stage A/B operate at the fragment (gap-based-burst) granularity; Stage C
operates at user-episode granularity (sequence_dataset.py). Fusion happens
at the EPISODE level — the same granularity Phase 2's industry-baseline
evaluation used — by aggregating Stage A/B's per-fragment scores for a
given episode via MAX (if any fragment looked suspicious, the episode is
at least that suspicious) before combining with Stage C's single score.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

DEFAULT_WEIGHT_A = 0.25
DEFAULT_WEIGHT_B = 0.45
DEFAULT_WEIGHT_C = 0.30

# Stage A's score is an unbounded, roughly-z-like magnitude (see
# stage_a_statistical.py), not a [0,1] probability. A score at or above
# this cap is treated as maximally suspicious for fusion purposes -- 5.0 is
# 2.5x the flag threshold (2.0), comfortably past "obviously anomalous."
STAGE_A_NORMALIZATION_CAP = 5.0


@dataclass(frozen=True)
class FusionWeights:
    weight_a: float = DEFAULT_WEIGHT_A
    weight_b: float = DEFAULT_WEIGHT_B
    weight_c: float = DEFAULT_WEIGHT_C

    def normalized(self) -> "FusionWeights":
        total = self.weight_a + self.weight_b + self.weight_c
        if total <= 0:
            return FusionWeights(0.0, 0.0, 0.0)
        return FusionWeights(self.weight_a / total, self.weight_b / total, self.weight_c / total)


def normalize_stage_a_score(raw_score: float, cap: float = STAGE_A_NORMALIZATION_CAP) -> float:
    return min(max(raw_score, 0.0) / cap, 1.0)


def fuse_scores(
    stage_a_raw_score: float,
    stage_b_calibrated_score: float,
    stage_c_probability: float,
    weights: FusionWeights = FusionWeights(),
) -> float:
    w = weights.normalized()
    a = normalize_stage_a_score(stage_a_raw_score)
    return w.weight_a * a + w.weight_b * stage_b_calibrated_score + w.weight_c * stage_c_probability


def aggregate_fragment_scores_to_episode(
    fragment_df: pd.DataFrame, episode_col: str, score_col: str
) -> dict:
    """MAX aggregation of a fragment-level score column up to episode
    granularity — see module docstring for why MAX (not mean): any single
    suspicious fragment should be enough to raise the whole episode's
    score, matching how a SOC analyst would read a flagged sub-event."""
    return fragment_df.groupby(episode_col)[score_col].max().to_dict()
