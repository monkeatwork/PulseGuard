"""Isotonic calibration of Stage B's raw scores (DECISIONS.md, "Stage B
(XGBoost) hyperparameters and calibration": isotonic chosen over Platt
scaling because tree ensembles produce non-sigmoidal score distributions).
"""

from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np
from sklearn.isotonic import IsotonicRegression


def fit_calibrator(raw_scores: np.ndarray, y_true: np.ndarray) -> IsotonicRegression:
    calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    calibrator.fit(raw_scores, y_true)
    return calibrator


def calibrate(calibrator: IsotonicRegression, raw_scores: np.ndarray) -> np.ndarray:
    return calibrator.predict(raw_scores)


def save_calibrator(calibrator: IsotonicRegression, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        pickle.dump(calibrator, f)


def load_calibrator(path: Path) -> IsotonicRegression:
    with path.open("rb") as f:
        return pickle.load(f)
