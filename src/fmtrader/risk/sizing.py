"""Position sizing — fractional Kelly, volatility targeting, fixed-fractional."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fmtrader.core.errors import RiskError


@dataclass(frozen=True)
class SizingConfig:
    kelly_fraction: float = 0.25
    max_risk_per_trade: float = 0.02  # fraction of equity
    target_vol: float = 0.10  # annualized target
    min_size: float = 0.0
    max_size: float = 1.0  # max fraction of equity notional


def binary_kelly(p: float, *, b: float = 1.0) -> float:
    """Full Kelly fraction for a binary bet with win prob ``p`` and net odds ``b``.

    f* = p - (1-p)/b   (for b:1 payout). For even-money (b=1): f* = 2p - 1.
    """
    if b <= 0:
        raise RiskError("odds b must be positive")
    return float(p - (1.0 - p) / b)


def fractional_kelly(
    p: float,
    *,
    b: float = 1.0,
    fraction: float = 0.25,
    max_risk_per_trade: float = 0.02,
    calibrated: bool = False,
) -> float:
    """Return position size as fraction of equity.

    Requires ``calibrated=True`` — uncalibrated probabilities are refused.
    """
    if not calibrated:
        raise RiskError(
            "Kelly rejects uncalibrated probabilities: calibrate (Platt/isotonic) first"
        )
    if not (0.0 <= p <= 1.0):
        raise RiskError(f"probability p must be in [0, 1], got {p}")
    if not (0.0 < fraction <= 1.0):
        raise RiskError(f"kelly_fraction must be in (0, 1], got {fraction}")

    full = binary_kelly(p, b=b)
    sized = max(0.0, full * fraction)
    return float(min(sized, max_risk_per_trade))


def vol_target_scale(
    realized_vol: float,
    *,
    target_vol: float = 0.10,
    max_leverage: float = 2.0,
) -> float:
    """Scale position inversely to realized vol: target_vol / realized_vol."""
    if realized_vol < 0:
        raise RiskError("realized_vol must be non-negative")
    if target_vol <= 0:
        raise RiskError("target_vol must be positive")
    if realized_vol == 0:
        return float(max_leverage)
    scale = target_vol / realized_vol
    return float(min(max(scale, 0.0), max_leverage))


def apply_vol_targeting(
    base_size: float,
    realized_vol: float,
    *,
    target_vol: float = 0.10,
    max_leverage: float = 2.0,
) -> float:
    return float(
        base_size * vol_target_scale(realized_vol, target_vol=target_vol, max_leverage=max_leverage)
    )


def fixed_fractional(equity: float, risk_fraction: float, stop_distance: float) -> float:
    """Units = (equity * risk_fraction) / stop_distance."""
    if equity <= 0 or stop_distance <= 0:
        raise RiskError("equity and stop_distance must be positive")
    if risk_fraction < 0:
        raise RiskError("risk_fraction must be non-negative")
    return float((equity * risk_fraction) / stop_distance)


def realized_vol_from_returns(returns: np.ndarray, *, periods_per_year: float = 252.0) -> float:
    r = np.asarray(returns, dtype=np.float64)
    if r.size < 2:
        return 0.0
    return float(np.std(r, ddof=1) * np.sqrt(periods_per_year))
