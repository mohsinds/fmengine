"""Trend indicators — trailing windows only."""

from __future__ import annotations

import numpy as np
import polars as pl
from pydantic import BaseModel, Field

from fmtrader.features.indicators._ops import (
    ema_numpy,
    series_from_numpy,
    true_range,
    wilder_smooth,
)
from fmtrader.features.registry import register_indicator


class PeriodParams(BaseModel):
    period: int = Field(default=20, ge=1)


class SupertrendParams(BaseModel):
    period: int = Field(default=10, ge=1)
    multiplier: float = Field(default=3.0, gt=0)


class IchimokuParams(BaseModel):
    tenkan: int = Field(default=9, ge=1)
    kijun: int = Field(default=26, ge=1)
    senkou_b: int = Field(default=52, ge=1)


@register_indicator(
    name="sma",
    category="trend",
    requires=("close",),
    min_lookback=lambda p: int(p["period"]),
    params_schema=PeriodParams,
)
def sma(df: pl.DataFrame, period: int = 20) -> pl.Series:
    """Simple moving average of close."""
    return (
        df.select(pl.col("close").rolling_mean(window_size=period).alias("sma"))
        .to_series()
        .rename(f"sma_{period}")
    )


@register_indicator(
    name="ema",
    category="trend",
    requires=("close",),
    min_lookback=lambda p: int(p["period"]),
    params_schema=PeriodParams,
)
def ema(df: pl.DataFrame, period: int = 20) -> pl.Series:
    """Exponential moving average (SMA-seeded)."""
    values = ema_numpy(df["close"].to_numpy().astype(np.float64), period)
    return series_from_numpy(values, name=f"ema_{period}", warmup=period - 1)


@register_indicator(
    name="wma",
    category="trend",
    requires=("close",),
    min_lookback=lambda p: int(p["period"]),
    params_schema=PeriodParams,
)
def wma(df: pl.DataFrame, period: int = 20) -> pl.Series:
    """Linearly weighted moving average."""
    weights = np.arange(1, period + 1, dtype=np.float64)
    wsum = float(weights.sum())
    close = df["close"].to_numpy().astype(np.float64)
    # convolve with reversed weights so latest bar gets highest weight
    conv = np.convolve(close, weights[::-1], mode="full")[: close.shape[0]] / wsum
    out = conv.astype(np.float64)
    out[: period - 1] = np.nan
    return series_from_numpy(out, name=f"wma_{period}", warmup=period - 1)


@register_indicator(
    name="hma",
    category="trend",
    requires=("close",),
    min_lookback=lambda p: int(p["period"]) + int(np.sqrt(int(p["period"]))),
    params_schema=PeriodParams,
)
def hma(df: pl.DataFrame, period: int = 20) -> pl.Series:
    """Hull moving average."""
    half = max(1, period // 2)
    sqrt_p = max(1, int(np.sqrt(period)))
    wma_half = wma(df, period=half).to_numpy().astype(np.float64)
    wma_full = wma(df, period=period).to_numpy().astype(np.float64)
    raw = 2.0 * wma_half - wma_full
    raw_df = pl.DataFrame({"close": raw})
    out = wma(raw_df, period=sqrt_p).to_numpy().astype(np.float64)
    warmup = period + sqrt_p - 2
    return series_from_numpy(out, name=f"hma_{period}", warmup=warmup)


@register_indicator(
    name="dema",
    category="trend",
    requires=("close",),
    min_lookback=lambda p: 2 * int(p["period"]) - 1,
    params_schema=PeriodParams,
)
def dema(df: pl.DataFrame, period: int = 20) -> pl.Series:
    """Double EMA."""
    e1 = ema_numpy(df["close"].to_numpy().astype(np.float64), period)
    e2 = ema_numpy(e1, period)
    out = 2.0 * e1 - e2
    return series_from_numpy(out, name=f"dema_{period}", warmup=2 * period - 2)


@register_indicator(
    name="tema",
    category="trend",
    requires=("close",),
    min_lookback=lambda p: 3 * int(p["period"]) - 2,
    params_schema=PeriodParams,
)
def tema(df: pl.DataFrame, period: int = 20) -> pl.Series:
    """Triple EMA."""
    e1 = ema_numpy(df["close"].to_numpy().astype(np.float64), period)
    e2 = ema_numpy(e1, period)
    e3 = ema_numpy(e2, period)
    out = 3.0 * e1 - 3.0 * e2 + e3
    return series_from_numpy(out, name=f"tema_{period}", warmup=3 * period - 3)


@register_indicator(
    name="adx",
    category="trend",
    requires=("high", "low", "close"),
    min_lookback=lambda p: 2 * int(p["period"]),
    params_schema=PeriodParams,
    multi_output=True,
    output_columns=("adx", "plus_di", "minus_di"),
)
def adx(df: pl.DataFrame, period: int = 14) -> pl.DataFrame:
    """Average Directional Index with +DI / -DI."""
    high = df["high"].to_numpy().astype(np.float64)
    low = df["low"].to_numpy().astype(np.float64)
    close = df["close"].to_numpy().astype(np.float64)
    n = close.shape[0]
    up = np.zeros(n)
    down = np.zeros(n)
    up[1:] = high[1:] - high[:-1]
    down[1:] = low[:-1] - low[1:]
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = true_range(high, low, close)
    atr = wilder_smooth(tr, period)
    plus_sm = wilder_smooth(plus_dm, period)
    minus_sm = wilder_smooth(minus_dm, period)
    plus_di = 100.0 * plus_sm / np.where(atr == 0, np.nan, atr)
    minus_di = 100.0 * minus_sm / np.where(atr == 0, np.nan, atr)
    dx = (
        100.0
        * np.abs(plus_di - minus_di)
        / np.where((plus_di + minus_di) == 0, np.nan, plus_di + minus_di)
    )
    adx_v = wilder_smooth(dx, period)
    warmup = 2 * period - 1
    return pl.DataFrame(
        {
            f"adx_{period}": series_from_numpy(adx_v, name=f"adx_{period}", warmup=warmup),
            f"plus_di_{period}": series_from_numpy(
                plus_di, name=f"plus_di_{period}", warmup=period - 1
            ),
            f"minus_di_{period}": series_from_numpy(
                minus_di, name=f"minus_di_{period}", warmup=period - 1
            ),
        }
    )


@register_indicator(
    name="aroon",
    category="trend",
    requires=("high", "low"),
    min_lookback=lambda p: int(p["period"]),
    params_schema=PeriodParams,
    multi_output=True,
    output_columns=("aroon_up", "aroon_down"),
)
def aroon(df: pl.DataFrame, period: int = 25) -> pl.DataFrame:
    """Aroon up/down over ``period`` bars."""
    high = df["high"].to_numpy().astype(np.float64)
    low = df["low"].to_numpy().astype(np.float64)
    n = high.shape[0]
    up = np.full(n, np.nan)
    down = np.full(n, np.nan)
    if n >= period:
        wh = np.lib.stride_tricks.sliding_window_view(high, period)
        wl = np.lib.stride_tricks.sliding_window_view(low, period)
        # bars since extremum within window of length `period`
        since_high = (period - 1) - np.argmax(wh, axis=1)
        since_low = (period - 1) - np.argmin(wl, axis=1)
        up[period - 1 :] = 100.0 * (period - 1 - since_high) / (period - 1 if period > 1 else 1)
        down[period - 1 :] = 100.0 * (period - 1 - since_low) / (period - 1 if period > 1 else 1)
    return pl.DataFrame(
        {
            f"aroon_up_{period}": series_from_numpy(
                up, name=f"aroon_up_{period}", warmup=period - 1
            ),
            f"aroon_down_{period}": series_from_numpy(
                down, name=f"aroon_down_{period}", warmup=period - 1
            ),
        }
    )


@register_indicator(
    name="supertrend",
    category="trend",
    requires=("high", "low", "close"),
    min_lookback=lambda p: int(p["period"]) + 1,
    params_schema=SupertrendParams,
)
def supertrend(df: pl.DataFrame, period: int = 10, multiplier: float = 3.0) -> pl.Series:
    """Supertrend line (ATR-based)."""
    high = df["high"].to_numpy().astype(np.float64)
    low = df["low"].to_numpy().astype(np.float64)
    close = df["close"].to_numpy().astype(np.float64)
    atr = wilder_smooth(true_range(high, low, close), period)
    mid = (high + low) / 2.0
    basic_ub = mid + multiplier * atr
    basic_lb = mid - multiplier * atr
    n = close.shape[0]
    final_ub = np.full(n, np.nan)
    final_lb = np.full(n, np.nan)
    st = np.full(n, np.nan)
    for i in range(period - 1, n):
        if i == period - 1:
            final_ub[i] = basic_ub[i]
            final_lb[i] = basic_lb[i]
            st[i] = final_ub[i] if close[i] <= final_ub[i] else final_lb[i]
            continue
        final_ub[i] = (
            basic_ub[i]
            if (basic_ub[i] < final_ub[i - 1] or close[i - 1] > final_ub[i - 1])
            else final_ub[i - 1]
        )
        final_lb[i] = (
            basic_lb[i]
            if (basic_lb[i] > final_lb[i - 1] or close[i - 1] < final_lb[i - 1])
            else final_lb[i - 1]
        )
        if st[i - 1] == final_ub[i - 1]:
            st[i] = final_ub[i] if close[i] <= final_ub[i] else final_lb[i]
        else:
            st[i] = final_lb[i] if close[i] >= final_lb[i] else final_ub[i]
    return series_from_numpy(st, name=f"supertrend_{period}_{multiplier:g}", warmup=period - 1)


@register_indicator(
    name="linreg_slope",
    category="trend",
    requires=("close",),
    min_lookback=lambda p: int(p["period"]),
    params_schema=PeriodParams,
)
def linreg_slope(df: pl.DataFrame, period: int = 20) -> pl.Series:
    """OLS slope of close over trailing ``period`` bars."""
    close = df["close"].to_numpy().astype(np.float64)
    n = close.shape[0]
    x = np.arange(period, dtype=np.float64)
    x_mean = x.mean()
    x_c = x - x_mean
    denom = float(np.dot(x_c, x_c))
    # slope = sum(x_c * y_c) / denom = (sum(x_c*y) - 0)/denom since sum(x_c)=0
    # = sum(x_c * y_window) / denom
    kernel = x_c[::-1]  # align with convolve
    numbered = np.convolve(close, kernel, mode="full")[:n]
    out = numbered / denom
    out[: period - 1] = np.nan
    return series_from_numpy(out, name=f"linreg_slope_{period}", warmup=period - 1)


@register_indicator(
    name="ichimoku",
    category="trend",
    requires=("high", "low", "close"),
    min_lookback=lambda p: int(p["senkou_b"]),
    params_schema=IchimokuParams,
    multi_output=True,
    output_columns=("tenkan", "kijun", "senkou_a", "senkou_b"),
)
def ichimoku(
    df: pl.DataFrame,
    tenkan: int = 9,
    kijun: int = 26,
    senkou_b: int = 52,
) -> pl.DataFrame:
    """Ichimoku components at bar time (no forward-shifted cloud plot).

    Senkou spans are reported as of the current bar (not displaced forward),
    so they remain causal for decision-making.
    """
    high = df["high"]
    low = df["low"]

    def mid_hl(period: int) -> pl.Series:
        return ((high.rolling_max(period) + low.rolling_min(period)) / 2).rename(f"mid_{period}")

    tenkan_s = mid_hl(tenkan).rename(f"ichimoku_tenkan_{tenkan}")
    kijun_s = mid_hl(kijun).rename(f"ichimoku_kijun_{kijun}")
    senkou_a = ((tenkan_s + kijun_s) / 2).rename(f"ichimoku_senkou_a_{tenkan}_{kijun}")
    senkou_b_s = mid_hl(senkou_b).rename(f"ichimoku_senkou_b_{senkou_b}")
    return pl.DataFrame(
        {
            tenkan_s.name: tenkan_s,
            kijun_s.name: kijun_s,
            senkou_a.name: senkou_a,
            senkou_b_s.name: senkou_b_s,
        }
    )
