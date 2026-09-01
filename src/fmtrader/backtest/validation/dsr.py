"""Deflated Sharpe Ratio (Bailey & López de Prado)."""

from __future__ import annotations

import math

from scipy.stats import norm


def expected_max_sharpe(*, n_trials: int, variance: float = 1.0) -> float:
    """Expected maximum Sharpe under the null for ``n_trials`` independent trials.

    Bailey & Lopez de Prado approximation:
      E[max SR] ~= (1-gamma) * Phi^{-1}(1-1/N) + gamma * Phi^{-1}(1-1/(N e))
    with gamma ~= 0.5772156649 (Euler-Mascheroni), scaled by sqrt(variance).
    """
    n = max(int(n_trials), 1)
    if n == 1:
        return 0.0
    gamma = 0.5772156649
    e = math.e
    z1 = norm.ppf(1.0 - 1.0 / n)
    z2 = norm.ppf(1.0 - 1.0 / (n * e))
    return float(((1.0 - gamma) * z1 + gamma * z2) * math.sqrt(variance))


def deflated_sharpe(
    observed_sharpe: float,
    *,
    n_trials: int,
    n_returns: int,
    skew: float = 0.0,
    kurtosis: float = 3.0,
    variance_under_null: float = 1.0,
) -> float:
    """Deflated Sharpe Ratio.

    DSR = Phi( [ (SR - SR*) * sqrt(n-1) ] / sqrt(1 - skew3*SR + ((kurt-1)/4)*SR^2) )

    Returns the probability that the observed SR is greater than the expected
    maximum under multiple testing (higher is better; < 0.5 is weak).
    For gate logic we also expose ``dsr_score = SR - SR*`` via ``deflated_sharpe_excess``.
    """
    excess = deflated_sharpe_excess(
        observed_sharpe,
        n_trials=n_trials,
        n_returns=n_returns,
        skew=skew,
        kurtosis=kurtosis,
        variance_under_null=variance_under_null,
    )
    return float(norm.cdf(excess))


def deflated_sharpe_excess(
    observed_sharpe: float,
    *,
    n_trials: int,
    n_returns: int,
    skew: float = 0.0,
    kurtosis: float = 3.0,
    variance_under_null: float = 1.0,
) -> float:
    """Signed excess of observed SR over the multiple-testing-adjusted benchmark."""
    sr = float(observed_sharpe)
    sr_star = expected_max_sharpe(n_trials=n_trials, variance=variance_under_null)
    n = max(int(n_returns), 2)
    denom = math.sqrt(max(1e-12, 1.0 - skew * sr + ((kurtosis - 1.0) / 4.0) * sr * sr))
    return ((sr - sr_star) * math.sqrt(n - 1)) / denom
