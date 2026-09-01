"""Regime features — trailing quantile rank only (no full-sample fit)."""

from __future__ import annotations

import numpy as np
import polars as pl
from pydantic import BaseModel, Field

from fmtrader.features.indicators._ops import series_from_numpy
from fmtrader.features.indicators.volatility import realized_vol
from fmtrader.features.registry import register_indicator


class QuantileVolRegimeParams(BaseModel):
    vol_period: int = Field(default=20, ge=2)
    rank_window: int = Field(default=1440, ge=10)  # ~1 trading day of M1
    # Fixed bucket edges in [0, 1] — NOT fit on the full sample
    low_q: float = Field(default=0.33, gt=0, lt=1)
    high_q: float = Field(default=0.66, gt=0, lt=1)


@register_indicator(
    name="quantile_vol_regime",
    category="regime",
    requires=("close",),
    min_lookback=lambda p: int(p["vol_period"]) + int(p["rank_window"]),
    params_schema=QuantileVolRegimeParams,
)
def quantile_vol_regime(
    df: pl.DataFrame,
    vol_period: int = 20,
    rank_window: int = 1440,
    low_q: float = 0.33,
    high_q: float = 0.66,
) -> pl.Series:
    """Discrete vol regime from trailing percentile rank of realized vol.

    Regime codes: 0=low, 1=mid, 2=high. Bucket edges are config-fixed.
    """
    if not (0.0 < low_q < high_q < 1.0):
        raise ValueError("Require 0 < low_q < high_q < 1")
    vol = realized_vol(df, period=vol_period).to_numpy().astype(np.float64)
    n = vol.shape[0]
    rank = np.full(n, np.nan)
    warmup = vol_period + rank_window - 1
    if n >= rank_window:
        filled = np.where(np.isnan(vol), 0.0, vol)
        nan_mask = np.isnan(vol)
        windows = np.lib.stride_tricks.sliding_window_view(filled, rank_window)
        nan_win = np.lib.stride_tricks.sliding_window_view(nan_mask, rank_window)
        start = rank_window - 1
        # Chunk comparisons to avoid materializing (n * rank_window) bools at once
        chunk = 8_192
        n_win = windows.shape[0]
        frac = np.empty(n_win, dtype=np.float64)
        valid = np.empty(n_win, dtype=bool)
        for i0 in range(0, n_win, chunk):
            i1 = min(n_win, i0 + chunk)
            w = windows[i0:i1]
            frac[i0:i1] = np.mean(w[:, :-1] < w[:, -1:], axis=1)
            valid[i0:i1] = ~nan_win[i0:i1].any(axis=1)
        rank[start:] = np.where(valid, frac, np.nan)
    regime = np.full(n, np.nan)
    valid_rank = ~np.isnan(rank)
    regime[valid_rank & (rank <= low_q)] = 0.0
    regime[valid_rank & (rank > low_q) & (rank <= high_q)] = 1.0
    regime[valid_rank & (rank > high_q)] = 2.0
    # Enforce warmup nulls even if early windows were numerically defined
    name = f"vol_regime_{vol_period}_{rank_window}"
    return series_from_numpy(regime, name=name, warmup=warmup)
