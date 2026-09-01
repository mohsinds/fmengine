"""Shared helpers for indicator implementations (trailing windows only)."""

from __future__ import annotations

import numpy as np
import polars as pl


def null_prefix(n: int, warmup: int) -> pl.Expr:
    """Mask the first ``warmup`` rows as null (0-based count)."""
    return pl.when(pl.int_range(0, n) < warmup).then(None).otherwise(pl.lit(True))


def series_from_numpy(values: np.ndarray, *, name: str, warmup: int) -> pl.Series:
    """Build a Polars Series with leading warmup nulls from a float array."""
    out = values.astype(np.float64, copy=True)
    if warmup > 0:
        out[:warmup] = np.nan
    return pl.Series(name, out).fill_nan(None)


def wilder_smooth(x: np.ndarray, period: int) -> np.ndarray:
    """Wilder / RMA smoothing. First non-null at index ``period - 1`` is SMA seed."""
    out = np.full(x.shape[0], np.nan, dtype=np.float64)
    if period < 1 or x.shape[0] < period:
        return out
    seed_window = x[:period]
    if np.all(np.isnan(seed_window)):
        return out
    seed = float(np.nanmean(seed_window))
    if np.isnan(seed):
        return out
    out[period - 1] = seed
    alpha = 1.0 / period
    for i in range(period, x.shape[0]):
        prev = out[i - 1]
        xi = x[i]
        if np.isnan(xi) or np.isnan(prev):
            out[i] = np.nan
        else:
            out[i] = prev + alpha * (xi - prev)
    return out


def true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    """True range; index 0 uses high-low only (no prior close)."""
    prev_close = np.empty_like(close)
    prev_close[0] = np.nan
    prev_close[1:] = close[:-1]
    hl = high - low
    hc = np.abs(high - prev_close)
    lc = np.abs(low - prev_close)
    tr = np.nanmax(np.vstack([hl, hc, lc]), axis=0)
    tr[0] = hl[0]
    return tr


def ema_numpy(x: np.ndarray, period: int) -> np.ndarray:
    """EMA with SMA seed at index period-1; prior values NaN."""
    out = np.full(x.shape[0], np.nan, dtype=np.float64)
    if period < 1 or x.shape[0] < period:
        return out
    seed_window = x[:period]
    if np.all(np.isnan(seed_window)):
        return out
    out[period - 1] = float(np.nanmean(seed_window))
    if np.isnan(out[period - 1]):
        return out
    alpha = 2.0 / (period + 1)
    for i in range(period, x.shape[0]):
        out[i] = alpha * x[i] + (1.0 - alpha) * out[i - 1]
    return out


def rolling_sum_valid(x: np.ndarray, window: int) -> np.ndarray:
    """Trailing sum; NaN until window filled."""
    out = np.full(x.shape[0], np.nan, dtype=np.float64)
    if window < 1:
        return out
    c = np.cumsum(np.nan_to_num(x, nan=0.0))
    out[window - 1 :] = c[window - 1 :] - np.concatenate([[0.0], c[:-window]])
    # invalidate if any nan in window — approximate via nan count
    isnan = np.isnan(x).astype(np.float64)
    cn = np.cumsum(isnan)
    nans = np.empty_like(cn)
    nans[: window - 1] = np.nan
    nans[window - 1 :] = cn[window - 1 :] - np.concatenate([[0.0], cn[:-window]])
    out[nans > 0] = np.nan
    return out
