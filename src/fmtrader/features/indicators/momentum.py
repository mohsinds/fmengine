"""Momentum indicators — trailing windows only."""

from __future__ import annotations

import numpy as np
import polars as pl
from pydantic import BaseModel, Field

from fmtrader.features.indicators._ops import ema_numpy, series_from_numpy, wilder_smooth
from fmtrader.features.registry import register_indicator


class PeriodParams(BaseModel):
    period: int = Field(default=14, ge=1)


class StochParams(BaseModel):
    k_period: int = Field(default=14, ge=1)
    d_period: int = Field(default=3, ge=1)


class MacdParams(BaseModel):
    fast: int = Field(default=12, ge=1)
    slow: int = Field(default=26, ge=1)
    signal: int = Field(default=9, ge=1)


class TsiParams(BaseModel):
    long_period: int = Field(default=25, ge=1)
    short_period: int = Field(default=13, ge=1)


@register_indicator(
    name="rsi",
    category="momentum",
    requires=("close",),
    min_lookback=lambda p: int(p["period"]) + 1,
    params_schema=PeriodParams,
)
def rsi(df: pl.DataFrame, period: int = 14) -> pl.Series:
    """Relative Strength Index (Wilder)."""
    close = df["close"].to_numpy().astype(np.float64)
    delta = np.diff(close, prepend=np.nan)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    gain[0] = np.nan
    loss[0] = np.nan
    avg_gain = wilder_smooth(gain, period)
    avg_loss = wilder_smooth(loss, period)
    rs = avg_gain / np.where(avg_loss == 0, np.nan, avg_loss)
    out = 100.0 - (100.0 / (1.0 + rs))
    out = np.where(avg_loss == 0, 100.0, out)
    out = np.where((avg_gain == 0) & (avg_loss == 0), 50.0, out)
    return series_from_numpy(out, name=f"rsi_{period}", warmup=period)


@register_indicator(
    name="stochastic",
    category="momentum",
    requires=("high", "low", "close"),
    min_lookback=lambda p: int(p["k_period"]) + int(p["d_period"]) - 1,
    params_schema=StochParams,
    multi_output=True,
    output_columns=("stoch_k", "stoch_d"),
)
def stochastic(df: pl.DataFrame, k_period: int = 14, d_period: int = 3) -> pl.DataFrame:
    """Stochastic %K / %D."""
    lowest = df["low"].rolling_min(k_period)
    highest = df["high"].rolling_max(k_period)
    k_expr = (
        pl.when(highest == lowest)
        .then(None)
        .otherwise((df["close"] - lowest) / (highest - lowest) * 100.0)
    )
    k_name = f"stoch_k_{k_period}"
    d_name = f"stoch_d_{k_period}_{d_period}"
    return df.select(
        k_expr.alias(k_name),
        k_expr.rolling_mean(d_period).alias(d_name),
    )


@register_indicator(
    name="cci",
    category="momentum",
    requires=("high", "low", "close"),
    min_lookback=lambda p: int(p["period"]),
    params_schema=PeriodParams,
)
def cci(df: pl.DataFrame, period: int = 20) -> pl.Series:
    """Commodity Channel Index."""
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    sma = tp.rolling_mean(period)
    mad = (tp - sma).abs().rolling_mean(period)
    out = pl.when(mad == 0).then(None).otherwise((tp - sma) / (0.015 * mad))
    return df.select(out.alias(f"cci_{period}")).to_series()


@register_indicator(
    name="willr",
    category="momentum",
    requires=("high", "low", "close"),
    min_lookback=lambda p: int(p["period"]),
    params_schema=PeriodParams,
)
def willr(df: pl.DataFrame, period: int = 14) -> pl.Series:
    """Williams %R."""
    highest = df["high"].rolling_max(period)
    lowest = df["low"].rolling_min(period)
    out = (
        pl.when(highest == lowest)
        .then(None)
        .otherwise(-100.0 * (highest - df["close"]) / (highest - lowest))
    )
    return df.select(out.alias(f"willr_{period}")).to_series()


@register_indicator(
    name="roc",
    category="momentum",
    requires=("close",),
    min_lookback=lambda p: int(p["period"]) + 1,
    params_schema=PeriodParams,
)
def roc(df: pl.DataFrame, period: int = 10) -> pl.Series:
    """Rate of change (%)."""
    prev = df["close"].shift(period)
    out = (df["close"] - prev) / prev * 100.0
    return df.select(out.alias(f"roc_{period}")).to_series()


@register_indicator(
    name="macd",
    category="momentum",
    requires=("close",),
    min_lookback=lambda p: int(p["slow"]) + int(p["signal"]) - 1,
    params_schema=MacdParams,
    multi_output=True,
    output_columns=("macd", "macd_signal", "macd_hist", "macd_hist_slope"),
)
def macd(
    df: pl.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pl.DataFrame:
    """MACD line, signal, histogram, and histogram slope (1-bar diff)."""
    close = df["close"].to_numpy().astype(np.float64)
    line = ema_numpy(close, fast) - ema_numpy(close, slow)
    sig = ema_numpy(line, signal)
    hist = line - sig
    slope = np.empty_like(hist)
    slope[0] = np.nan
    slope[1:] = hist[1:] - hist[:-1]
    warmup = slow + signal - 2
    return pl.DataFrame(
        {
            f"macd_{fast}_{slow}": series_from_numpy(
                line, name=f"macd_{fast}_{slow}", warmup=slow - 1
            ),
            f"macd_signal_{fast}_{slow}_{signal}": series_from_numpy(
                sig, name=f"macd_signal_{fast}_{slow}_{signal}", warmup=warmup
            ),
            f"macd_hist_{fast}_{slow}_{signal}": series_from_numpy(
                hist, name=f"macd_hist_{fast}_{slow}_{signal}", warmup=warmup
            ),
            f"macd_hist_slope_{fast}_{slow}_{signal}": series_from_numpy(
                slope, name=f"macd_hist_slope_{fast}_{slow}_{signal}", warmup=warmup + 1
            ),
        }
    )


@register_indicator(
    name="tsi",
    category="momentum",
    requires=("close",),
    min_lookback=lambda p: int(p["long_period"]) + int(p["short_period"]),
    params_schema=TsiParams,
)
def tsi(df: pl.DataFrame, long_period: int = 25, short_period: int = 13) -> pl.Series:
    """True Strength Index."""
    close = df["close"].to_numpy().astype(np.float64)
    mom = np.diff(close, prepend=np.nan)
    mom[0] = np.nan
    double_smooth = ema_numpy(ema_numpy(mom, long_period), short_period)
    double_abs = ema_numpy(ema_numpy(np.abs(mom), long_period), short_period)
    out = 100.0 * double_smooth / np.where(double_abs == 0, np.nan, double_abs)
    warmup = long_period + short_period - 1
    return series_from_numpy(out, name=f"tsi_{long_period}_{short_period}", warmup=warmup)
