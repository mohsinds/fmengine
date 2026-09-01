"""DSR and PBO unit tests."""

from __future__ import annotations

import numpy as np

from fmtrader.backtest.validation.dsr import deflated_sharpe_excess, expected_max_sharpe
from fmtrader.backtest.validation.pbo import pbo_cscv


def test_dsr_decreases_as_trial_count_increases() -> None:
    # Excess of a fixed SR over SR* falls as N grows (SR* rises)
    e1 = deflated_sharpe_excess(1.0, n_trials=10, n_returns=5000)
    e2 = deflated_sharpe_excess(1.0, n_trials=10_000, n_returns=5000)
    assert e2 < e1
    assert expected_max_sharpe(n_trials=10_000) > expected_max_sharpe(n_trials=10)


def test_dsr_matches_reference_on_known_input() -> None:
    # SR* for N=1 is 0; excess for SR=0 should be ~0
    e = deflated_sharpe_excess(0.0, n_trials=1, n_returns=1000, skew=0.0, kurtosis=3.0)
    assert abs(e) < 1e-9


def test_pbo_near_one_for_pure_noise_strategies() -> None:
    """Spurious group-local edges (no true skill) → CSCV PBO near 1.

    Each trial is long on a random half of contiguous groups and short on the
    rest. IS selection then systematically picks the OOS loser.
    """
    rng = np.random.default_rng(0)
    n_trials, n_bars, n_groups = 64, 2048, 16
    r = np.zeros((n_trials, n_bars), dtype=np.float64)
    edges = np.linspace(0, n_bars, n_groups + 1, dtype=int)
    for i in range(n_trials):
        preferred = set(rng.choice(n_groups, size=n_groups // 2, replace=False).tolist())
        for g in range(n_groups):
            r[i, edges[g] : edges[g + 1]] = 0.01 if g in preferred else -0.01
    pbo = pbo_cscv(r, n_groups=n_groups, max_combinations=400)
    assert pbo > 0.8


def test_pbo_low_for_a_synthetic_real_edge() -> None:
    rng = np.random.default_rng(1)
    n_trials, n_bars = 50, 2000
    r = rng.normal(0, 0.001, size=(n_trials, n_bars))
    # Plant one consistently positive edge trial
    r[0] = 0.002 + rng.normal(0, 0.0002, size=n_bars)
    pbo = pbo_cscv(r, n_groups=16, max_combinations=300)
    assert pbo < 0.5
