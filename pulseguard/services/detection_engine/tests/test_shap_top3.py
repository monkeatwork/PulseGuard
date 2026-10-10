"""SHAP top-3 must surface a response-behaviour feature as a leading reason
for a known high-risk example -- proving the contribution feature family is
actually load-bearing in the trained model, not merely present in the
feature vector (CLAUDE.md, "The core insight")."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from services.detection_engine.app.explain_shap import make_explainer, top3_reasons
from services.detection_engine.app.feature_table import RESPONSE_BEHAVIOUR_COLUMNS, to_model_matrix
from services.detection_engine.app.stage_b_xgboost import train_stage_b


def _row(**overrides) -> dict:
    base = dict(
        n_prompts=1, prompts_per_window=1, inter_prompt_mean=60.0, inter_prompt_std=5.0,
        burst_duration_seconds=30.0, off_hours_flag=False, geo_novelty=False, device_novelty=False,
        deny_run_length=0, capitulation_flag=False, approval_latency_z=0.0, approval_latency_z_valid=True,
        latency_drift_slope=0.0, latency_drift_slope_valid=False, post_burst_approval_gap_seconds=0.0,
        post_burst_approval_gap_valid=False, denial_latency_variance=0.0, denial_latency_variance_valid=False,
        baseline_is_cold_start=True,
    )
    base.update(overrides)
    return base


@pytest.fixture(scope="module")
def trained_model_and_data():
    """Frequency features (n_prompts, prompts_per_window, inter_prompt_mean)
    are drawn from the SAME distribution regardless of label -- deliberately
    uninformative -- so the only signal available to Stage B is the
    response-behaviour block. This isolates what the test actually claims:
    that response-behaviour features are load-bearing, not just present.
    A synthetic setup where frequency trivially separates the classes (as
    an earlier version of this test had) would let the model ignore
    response-behaviour features entirely while still passing, which
    defeats the point of the test."""
    rng = np.random.default_rng(42)
    rows = []
    labels = []
    for _ in range(1500):
        is_attack = rng.random() < 0.3
        shared_n_prompts = int(rng.integers(5, 9))  # same range for both classes
        if is_attack:
            row = _row(
                n_prompts=shared_n_prompts,
                deny_run_length=int(rng.integers(5, 15)),
                capitulation_flag=True,
                latency_drift_slope=float(rng.normal(-900, 150)),
                latency_drift_slope_valid=True,
                denial_latency_variance=float(rng.normal(500, 100)),
                denial_latency_variance_valid=True,
            )
        else:
            row = _row(n_prompts=shared_n_prompts, latency_drift_slope_valid=True)
        rows.append(row)
        labels.append(is_attack)

    table = pd.DataFrame(rows)
    table["label_attack"] = labels
    X = to_model_matrix(table)
    y = table["label_attack"]
    split = int(len(table) * 0.8)
    model = train_stage_b(X.iloc[:split], y.iloc[:split], X.iloc[split:], y.iloc[split:])
    return model, table


def test_response_behaviour_feature_appears_in_top3_for_high_risk_example(trained_model_and_data):
    model, table = trained_model_and_data
    explainer = make_explainer(model)

    high_risk_row = pd.DataFrame(
        [
            _row(
                n_prompts=15, deny_run_length=12, capitulation_flag=True,
                latency_drift_slope=-950.0, latency_drift_slope_valid=True,
                denial_latency_variance=600.0, denial_latency_variance_valid=True,
            )
        ]
    )

    reasons = top3_reasons(explainer, high_risk_row)
    assert len(reasons) == 3
    top3_feature_names = {r["feature"] for r in reasons}
    assert top3_feature_names & set(RESPONSE_BEHAVIOUR_COLUMNS), (
        f"expected a response-behaviour feature in {top3_feature_names}"
    )


def test_ordinary_benign_example_shap_reasons_are_well_formed(trained_model_and_data):
    """A prototypical benign example (no deny run, stationary latency) can
    legitimately have a large-magnitude SHAP value for its most decisive
    feature -- that is what makes it a prototypical case of its class, not
    a sign of a bug. This test checks the reasons are well-formed (finite,
    ranked by magnitude, referencing real feature values), not that the
    magnitude is small."""
    model, table = trained_model_and_data
    explainer = make_explainer(model)
    benign_row = pd.DataFrame([_row(n_prompts=6, deny_run_length=0, latency_drift_slope_valid=True)])
    reasons = top3_reasons(explainer, benign_row)
    assert len(reasons) == 3
    magnitudes = [abs(r["shap_value"]) for r in reasons]
    assert magnitudes == sorted(magnitudes, reverse=True)
    for r in reasons:
        assert np.isfinite(r["shap_value"])
        assert r["feature"] in benign_row.columns
