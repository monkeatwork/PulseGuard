from __future__ import annotations

import numpy as np

from services.detection_engine.app.calibration import calibrate, fit_calibrator


def test_calibrated_output_is_monotonic_non_decreasing_with_raw_score():
    rng = np.random.default_rng(0)
    raw_scores = rng.uniform(0, 1, 500)
    y_true = (raw_scores + rng.normal(0, 0.1, 500) > 0.5).astype(int)

    calibrator = fit_calibrator(raw_scores, y_true)

    order = np.argsort(raw_scores)
    calibrated_sorted = calibrate(calibrator, raw_scores[order])
    diffs = np.diff(calibrated_sorted)
    assert (diffs >= -1e-9).all()  # non-decreasing, allowing floating point noise


def test_calibrated_output_stays_within_unit_interval():
    rng = np.random.default_rng(1)
    raw_scores = rng.uniform(-5, 5, 200)  # deliberately out-of-range raw scores
    y_true = (raw_scores > 0).astype(int)
    calibrator = fit_calibrator(raw_scores, y_true)
    calibrated = calibrate(calibrator, raw_scores)
    assert (calibrated >= 0.0).all()
    assert (calibrated <= 1.0).all()


def test_perfectly_separable_scores_calibrate_to_extremes():
    raw_scores = np.array([0.0, 0.1, 0.2, 0.8, 0.9, 1.0])
    y_true = np.array([0, 0, 0, 1, 1, 1])
    calibrator = fit_calibrator(raw_scores, y_true)
    calibrated = calibrate(calibrator, raw_scores)
    assert calibrated[0] < 0.5
    assert calibrated[-1] > 0.5
