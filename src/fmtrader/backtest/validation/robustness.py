"""Robustness checks for candidate strategies."""

from __future__ import annotations

from typing import Any

import numpy as np

from fmtrader.backtest.enrichment import TradeRecord


def top_k_trade_removal(
    trades: list[TradeRecord],
    *,
    k: int = 5,
) -> dict[str, Any]:
    """Report net P&L with and without the best ``k`` trades."""
    if not trades:
        return {"k": k, "full_net": 0.0, "without_top_k": 0.0, "drag_pct": 0.0}
    pnls = np.array([t.pnl_net for t in trades], dtype=np.float64)
    full = float(pnls.sum())
    order = np.argsort(pnls)[::-1]
    drop = order[: min(k, pnls.size)]
    without = float(np.delete(pnls, drop).sum())
    drag = 0.0 if full == 0 else (full - without) / abs(full) * 100.0
    return {
        "k": k,
        "full_net": full,
        "without_top_k": without,
        "drag_pct": drag,
        "fragile_to_outliers": drag > 50.0,
    }


def parameter_neighborhood_stability(
    center_sharpe: float,
    neighbor_sharpes: list[float],
    *,
    rel_tol: float = 0.5,
) -> dict[str, Any]:
    """True if neighbors are not knife-edge (within relative tolerance of center)."""
    if not neighbor_sharpes:
        return {"stable": False, "reason": "no neighbors"}
    arr = np.array(neighbor_sharpes, dtype=np.float64)
    if center_sharpe == 0:
        stable = bool(np.all(np.abs(arr) < 0.1))
    else:
        stable = bool(np.mean(np.abs(arr - center_sharpe) / abs(center_sharpe)) <= rel_tol)
    return {
        "stable": stable,
        "center": center_sharpe,
        "neighbor_mean": float(arr.mean()),
        "neighbor_std": float(arr.std(ddof=0)),
    }
