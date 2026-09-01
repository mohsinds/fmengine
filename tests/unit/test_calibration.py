"""Calibration unit tests."""

from __future__ import annotations

import numpy as np

from fmtrader.models.calibration import (
    brier_score,
    calibrate,
    calibration_curve,
)


def test_isotonic_improves_brier_score_on_fixture() -> None:
    rng = np.random.default_rng(0)
    # Overconfident raw scores
    n = 400
    latent = rng.normal(0, 1, size=n)
    y = (latent > 0).astype(float)
    # Mis-scaled scores (too extreme)
    scores = 3.0 * latent
    raw_p = 1.0 / (1.0 + np.exp(-scores))
    raw_brier = brier_score(y, raw_p)
    calibrated, _ = calibrate(scores, y, method="isotonic")
    cal_brier = brier_score(y, calibrated.values)
    assert cal_brier <= raw_brier + 1e-9


def test_calibration_curve_within_tolerance() -> None:
    rng = np.random.default_rng(1)
    n = 500
    p_true = rng.uniform(0.1, 0.9, size=n)
    y = (rng.random(n) < p_true).astype(float)
    # Use true probs as "calibrated"
    conf, acc = calibration_curve(y, p_true, n_bins=8)
    # Mean absolute gap should be modest
    gap = float(np.mean(np.abs(conf - acc)))
    assert gap < 0.15
