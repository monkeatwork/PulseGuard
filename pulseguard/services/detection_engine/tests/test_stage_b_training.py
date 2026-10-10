"""Stage B trains on a synthetic feature table with a genuine learnable
response-behaviour signal and must actually learn it (val logloss
decreases with more estimators considered, and held-out AUC is well above
chance) -- not just run without crashing."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import roc_auc_score

from services.detection_engine.app.feature_table import FEATURE_COLUMNS, to_model_matrix
from services.detection_engine.app.stage_b_xgboost import predict_proba, train_stage_b


def _synthetic_feature_table(n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        is_attack = rng.random() < 0.3
        if is_attack:
            deny_run = rng.integers(2, 10)
            slope = rng.normal(-800, 200)
            n_prompts = rng.integers(5, 20)
        else:
            deny_run = 0
            slope = rng.normal(0, 50)
            n_prompts = 1
        rows.append(
            {
                "n_prompts": n_prompts,
                "prompts_per_window": n_prompts,
                "inter_prompt_mean": rng.normal(60, 10),
                "inter_prompt_std": rng.normal(10, 2),
                "burst_duration_seconds": n_prompts * 30,
                "off_hours_flag": bool(rng.random() < 0.1),
                "geo_novelty": bool(rng.random() < 0.1),
                "device_novelty": bool(rng.random() < 0.1),
                "deny_run_length": deny_run,
                "capitulation_flag": deny_run >= 2,
                "approval_latency_z": rng.normal(0, 1),
                "approval_latency_z_valid": True,
                "latency_drift_slope": slope,
                "latency_drift_slope_valid": n_prompts > 1,
                "post_burst_approval_gap_seconds": rng.normal(30, 5),
                "post_burst_approval_gap_valid": deny_run > 0,
                "denial_latency_variance": rng.normal(1000, 200) if deny_run >= 2 else 0.0,
                "denial_latency_variance_valid": deny_run >= 2,
                "baseline_is_cold_start": True,
                "label_attack": is_attack,
                "user_id": f"user{i}",
            }
        )
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def trained_model():
    train_table = _synthetic_feature_table(2000, seed=1)
    val_table = _synthetic_feature_table(500, seed=2)
    X_train = to_model_matrix(train_table)
    y_train = train_table["label_attack"]
    X_val = to_model_matrix(val_table)
    y_val = val_table["label_attack"]
    model = train_stage_b(X_train, y_train, X_val, y_val)
    return model, val_table, y_val


def test_model_learns_the_synthetic_signal(trained_model):
    model, val_table, y_val = trained_model
    proba = predict_proba(model, val_table)
    auc = roc_auc_score(y_val, proba)
    assert auc > 0.9  # the synthetic signal is strong and clean; should be nearly separable


def test_early_stopping_selected_a_reasonable_iteration_count(trained_model):
    model, _, _ = trained_model
    assert model.best_iteration is not None
    assert 0 < model.best_iteration <= 300


def test_predict_proba_returns_values_in_unit_interval(trained_model):
    model, val_table, _ = trained_model
    proba = predict_proba(model, val_table)
    assert (proba >= 0.0).all()
    assert (proba <= 1.0).all()
