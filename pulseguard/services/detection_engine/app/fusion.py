"""Combines Stage A, Stage B, and Stage C scores into one fused score per
user-episode (CLAUDE.md, L4 architecture: "Weighted fusion"). Initial
weights per DECISIONS.md, "Fusion weights and threshold placement":
0.25*A + 0.45*B + 0.30*C, retuned only via a documented grid search over
the validation split (tune_fusion_weights.py) — never silently, never
touching the test split.

All three stages score the same object -- a session-so-far at one decision
point (feature_table.py / sequence_dataset.py) -- so fusion is a per-
decision-point weighted sum. An episode's fused score is the MAX over its
decision points (episode_eval.py), matching the live rule that the first
crossing raises the alert. The weights used live are the ones persisted in
model_registry/operating_point.json, never these defaults.
"""

from __future__ import annotations

from dataclasses import dataclass

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
