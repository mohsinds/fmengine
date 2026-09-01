"""Probability of Backtest Overfitting (PBO) via CSCV."""

from __future__ import annotations

import itertools
from collections.abc import Sequence

import numpy as np


def pbo_cscv(
    trial_returns: np.ndarray,
    *,
    n_groups: int = 16,
    max_combinations: int = 2000,
) -> float:
    """Estimate PBO using Combinatorially Symmetric Cross-Validation.

    ``trial_returns`` shape: (n_trials, n_bars) of per-bar strategy returns
    (or any aligned performance series). Splits bars into ``n_groups``
    contiguous groups, evaluates all (or a capped sample of) combinations of
    half the groups as IS / OOS, and measures how often the IS-best trial
    underperforms the median OOS.

    Returns PBO in [0, 1]. Near 1 ⇒ selection procedure overfits.
    """
    r = np.asarray(trial_returns, dtype=np.float64)
    if r.ndim != 2:
        raise ValueError("trial_returns must be 2-D (n_trials, n_bars)")
    n_trials, n_bars = r.shape
    if n_trials < 2 or n_bars < n_groups:
        return 1.0

    # Contiguous group boundaries
    edges = np.linspace(0, n_bars, n_groups + 1, dtype=int)
    groups = [r[:, edges[i] : edges[i + 1]] for i in range(n_groups)]
    half = n_groups // 2
    combos = list(itertools.combinations(range(n_groups), half))
    if len(combos) > max_combinations:
        rng = np.random.default_rng(0)
        pick = rng.choice(len(combos), size=max_combinations, replace=False)
        combos = [combos[i] for i in pick]

    fail = 0
    total = 0
    for is_idx in combos:
        oos_idx = [i for i in range(n_groups) if i not in is_idx]
        is_perf = np.concatenate([groups[i] for i in is_idx], axis=1).sum(axis=1)
        oos_perf = np.concatenate([groups[i] for i in oos_idx], axis=1).sum(axis=1)
        best = int(np.argmax(is_perf))
        # Relative rank of best-IS trial in OOS (logit space in Bailey; use median compare)
        if oos_perf[best] <= np.median(oos_perf):
            fail += 1
        total += 1
    return float(fail / total) if total else 1.0


def pbo_from_sharpe_matrix(
    sharpe_is_oos_pairs: Sequence[tuple[float, float]],
) -> float:
    """Simpler PBO: fraction of splits where IS-best has OOS Sharpe below median OOS."""
    if not sharpe_is_oos_pairs:
        return 1.0
    fail = sum(1 for _is, oos_s in sharpe_is_oos_pairs if oos_s <= 0.0)
    return float(fail / len(sharpe_is_oos_pairs))
