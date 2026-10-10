"""SHAP top-3 reasons for Stage B, via XGBoost's built-in exact TreeSHAP
(`pred_contribs=True`) rather than the separate `shap` package.

Same algorithm (Lundberg et al. TreeSHAP), same per-feature log-odds
contributions, without the shap/numba/llvmlite dependency chain -- which
matters for the live container's memory budget. Used only when Stage B is
the component that dominated an alert's fused score (explain.py, B4).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import xgboost as xgb

from services.detection_engine.app.feature_table import FEATURE_COLUMNS, to_model_matrix


class TreeShapExplainer:
    def __init__(self, model: xgb.XGBClassifier):
        self.booster = model.get_booster()

    def shap_values(self, matrix: pd.DataFrame) -> np.ndarray:
        contribs = self.booster.predict(xgb.DMatrix(matrix), pred_contribs=True)
        return np.asarray(contribs)[:, :-1]  # last column is the bias term


def make_explainer(model: xgb.XGBClassifier) -> TreeShapExplainer:
    return TreeShapExplainer(model)


def top3_reasons(explainer: TreeShapExplainer, feature_row: pd.DataFrame) -> list[dict]:
    """`feature_row` is a single-row feature table (raw feature_table.py
    output, not yet passed through to_model_matrix)."""
    matrix = to_model_matrix(feature_row, FEATURE_COLUMNS)
    row_values = explainer.shap_values(matrix)[0]
    ranked = sorted(zip(FEATURE_COLUMNS, row_values), key=lambda kv: abs(kv[1]), reverse=True)
    return [
        {"feature": name, "shap_value": float(value), "feature_value": float(matrix.iloc[0][name])}
        for name, value in ranked[:3]
    ]
