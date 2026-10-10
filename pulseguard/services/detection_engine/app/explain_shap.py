"""SHAP top-3 explanation per alert (CLAUDE.md, L4 architecture).

Verified against the installed shap==0.52.0 / xgboost==3.4.1: for a binary
XGBClassifier, `TreeExplainer.shap_values` returns a plain (n_rows,
n_features) array directly (not the list-of-arrays-per-class shape some
older SHAP/model combinations produce) — handled defensively below anyway
so a future version bump doesn't silently break `top3_reasons`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import shap
import xgboost as xgb

from services.detection_engine.app.feature_table import FEATURE_COLUMNS, to_model_matrix


def make_explainer(model: xgb.XGBClassifier) -> shap.TreeExplainer:
    return shap.TreeExplainer(model)


def top3_reasons(explainer: shap.TreeExplainer, feature_row: pd.DataFrame) -> list[dict]:
    """`feature_row` is a single-row feature table (raw feature_table.py
    output, not yet passed through to_model_matrix)."""
    matrix = to_model_matrix(feature_row, FEATURE_COLUMNS)
    shap_values = explainer.shap_values(matrix)
    if isinstance(shap_values, list):
        shap_values = shap_values[1]  # class-1 (attack) SHAP values
    row_values = np.asarray(shap_values)[0]

    ranked = sorted(zip(FEATURE_COLUMNS, row_values), key=lambda kv: abs(kv[1]), reverse=True)
    return [
        {
            "feature": name,
            "shap_value": float(value),
            "feature_value": float(matrix.iloc[0][name]),
        }
        for name, value in ranked[:3]
    ]
