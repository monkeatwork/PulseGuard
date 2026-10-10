"""REMEDIATION_TASK.md B4: the reasons shown for an alert come from the
component that actually drove its fused score, and say which one."""

from __future__ import annotations

import numpy as np
import torch

from services.detection_engine.app.explain import (
    STEP_FEATURE_NAMES,
    contributions,
    dominant_stage,
    stage_a_reasons,
    stage_c_reasons,
)
from services.detection_engine.app.fusion import FusionWeights
from services.detection_engine.app.sequence_dataset import SEQUENCE_LENGTH, STEP_FEATURE_DIM
from services.detection_engine.app.stage_c_gru import StageCGRU


def test_a_zero_weight_stage_can_never_be_the_explanation_source():
    contrib = contributions(a_raw=5.0, b=1.0, c=0.2, weights=FusionWeights(0.0, 0.0, 1.0))
    assert contrib["stage_a"] == 0.0 and contrib["stage_b"] == 0.0
    assert dominant_stage(contrib) == "stage_c"


def test_dominant_stage_follows_weighted_contribution_not_raw_score():
    # B's raw score is higher, but A carries more weight x score
    contrib = contributions(a_raw=5.0, b=0.9, c=0.1, weights=FusionWeights(0.6, 0.3, 0.1))
    assert dominant_stage(contrib) == "stage_a"


def test_stage_a_reasons_are_its_own_signals():
    reasons = stage_a_reasons({"deny_run_length": 8, "latency_drift_slope_valid": True, "latency_drift_slope": -600.0,
                               "approval_latency_z_valid": False, "prompts_per_window": 3})
    assert [r["feature"] for r in reasons] == ["deny_run_length", "latency_drift_slope"]
    assert reasons[0]["feature_value"] == 8


def test_stage_c_reasons_name_sequence_features():
    torch.manual_seed(0)
    seq = np.zeros((SEQUENCE_LENGTH, STEP_FEATURE_DIM), dtype=np.float32)
    seq[:5, 0] = 1.0
    seq[:5, 3] = 1.0
    seq[:5, 4] = np.log1p([4000, 3000, 2000, 1000, 600]) / 10
    reasons = stage_c_reasons(StageCGRU(), seq, 5)
    assert len(reasons) == 3
    assert all(r["feature"] in STEP_FEATURE_NAMES for r in reasons)
    denials = next((r for r in reasons if r["feature"] == "sequence: denials"), None)
    if denials:
        assert denials["feature_value"] == 5.0
