"""Stage B: XGBoost over the full frequency + response-behaviour feature
vector (CLAUDE.md, L4 architecture). Hyperparameters per DECISIONS.md,
"Stage B (XGBoost) hyperparameters and calibration".
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import xgboost as xgb

from services.detection_engine.app.feature_table import FEATURE_COLUMNS, to_model_matrix

XGB_PARAMS = dict(
    max_depth=5,
    n_estimators=300,
    learning_rate=0.05,
    objective="binary:logistic",
    eval_metric="logloss",
    early_stopping_rounds=20,
)


def train_stage_b(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
) -> xgb.XGBClassifier:
    model = xgb.XGBClassifier(**XGB_PARAMS)
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    return model


def predict_proba(model: xgb.XGBClassifier, feature_table: pd.DataFrame) -> pd.Series:
    matrix = to_model_matrix(feature_table, FEATURE_COLUMNS)
    return pd.Series(model.predict_proba(matrix)[:, 1], index=feature_table.index)


def save_model(model: xgb.XGBClassifier, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(str(path))


def load_model(path: Path) -> xgb.XGBClassifier:
    model = xgb.XGBClassifier()
    model.load_model(str(path))
    return model
