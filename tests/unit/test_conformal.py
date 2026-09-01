"""Conformal prediction unit tests."""

from __future__ import annotations

import numpy as np

from fmtrader.models.conformal import (
    SplitConformalClassifier,
    SplitConformalRegressor,
    empirical_coverage,
)
from fmtrader.risk.conformal_gate import ConformalGate, ConformalGateConfig


def test_empirical_coverage_matches_nominal_alpha() -> None:
    rng = np.random.default_rng(0)
    n_cal, n_test = 500, 300
    # y = x + noise; predictor = x
    x_cal = rng.normal(size=n_cal)
    y_cal = x_cal + rng.normal(scale=0.5, size=n_cal)
    x_test = rng.normal(size=n_test)
    y_test = x_test + rng.normal(scale=0.5, size=n_test)
    alpha = 0.1
    model = SplitConformalRegressor(alpha=alpha).fit(y_cal, x_cal)
    intervals = model.predict_interval(x_test)
    cov = empirical_coverage(y_test, intervals)
    # Coverage should be near 1-alpha (allow tolerance)
    assert abs(cov - (1 - alpha)) < 0.08


def test_wide_interval_triggers_skip() -> None:
    # Force a large qhat via high residual cal set
    y_cal = np.array([0.0, 1.0, 0.0, 1.0, 0.0, 1.0])
    p_cal = np.array([0.5, 0.5, 0.5, 0.5, 0.5, 0.5])
    model = SplitConformalClassifier(alpha=0.1).fit(y_cal, p_cal)
    gate = ConformalGate(model, ConformalGateConfig(max_width=0.2))
    decision = gate.evaluate(0.7)
    assert decision.allow is False
    assert "wide" in decision.reason


def test_gate_rejects_high_uncertainty_high_probability_signal() -> None:
    y_cal = np.linspace(0, 1, 40)
    p_cal = np.full(40, 0.5)
    model = SplitConformalClassifier(alpha=0.05).fit(y_cal, p_cal)
    gate = ConformalGate(
        model,
        ConformalGateConfig(max_width=0.15, reject_high_prob_if_wide=True, high_prob_threshold=0.6),
    )
    # 60%+ bullish but uncertain
    d = gate.evaluate(0.65)
    assert d.allow is False
    assert d.size_scale == 0.0
