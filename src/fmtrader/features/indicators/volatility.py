"""Volatility indicators — trailing windows only."""

from __future__ import annotations

import numpy as np
import polars as pl
from pydantic import BaseModel, Field

from fmtrader.features.indicators._ops import series_from_numpy, true_range, wilder_smooth
from fmtrader.features.registry import register_indicator


class PeriodParams(BaseModel):
    period: int = Field(default=14, ge=1)


class BbParams(BaseModel):
    period: int = Field(default=20, ge=1)
    num_std: float = Field(default=2.0, gt=0)


class KeltnerParams(BaseModel):
    period: int = Field(default=20, ge=1)
    atr_period: int = Field(default=10, ge=1)
    multiplier: float = Field(default=1.5, gt=0)


class ChaikinParams(BaseModel):
    ema_period: int = Field(default=10, ge=1)
    roc_period: int = Field(default=10, ge=1)


@register_indicator(
    name="atr",
    category="volatility",
    requires=("high", "low", "close"),
    min_lookback=lambda p: int(p["period"]) + 1,
    params_schema=PeriodParams,
)
def atr(df: pl.DataFrame, period: int = 14) -> pl.Series:
    """Average True Range (Wilder)."""
    high = df["high"].to_numpy().astype(np.float64)
    low = df["low"].to_numpy().astype(np.float64)
    close = df["close"].to_numpy().astype(np.float64)
    values = wilder_smooth(true_range(high, low, close), period)
    return series_from_numpy(values, name=f"atr_{period}", warmup=period - 1)


@register_indicator(
    name="natr",
    category="volatility",
    requires=("high", "low", "close"),
    min_lookback=lambda p: int(p["period"]) + 1,
    params_schema=PeriodParams,
)
def natr(df: pl.DataFrame, period: int = 14) -> pl.Series:
    """Normalized ATR (% of close)."""
    a = atr(df, period=period).to_numpy().astype(np.float64)
    close = df["close"].to_numpy().astype(np.float64)
    out = 100.0 * a / np.where(close == 0, np.nan, close)
    return series_from_numpy(out, name=f"natr_{period}", warmup=period - 1)


@register_indicator(
    name="bollinger",
    category="volatility",
    requires=("close",),
    min_lookback=lambda p: int(p["period"]),
    params_schema=BbParams,
    multi_output=True,
    output_columns=("bb_mid", "bb_upper", "bb_lower", "bb_pctb", "bb_bandwidth"),
)
def bollinger(df: pl.DataFrame, period: int = 20, num_std: float = 2.0) -> pl.DataFrame:
    """Bollinger mid/upper/lower, %B, and bandwidth."""
    mid = df["close"].rolling_mean(period)
    std = df["close"].rolling_std(period, ddof=0)
    upper = mid + num_std * std
    lower = mid - num_std * std
    width = upper - lower
    pctb = pl.when(width == 0).then(None).otherwise((df["close"] - lower) / width)
    bw = pl.when(mid == 0).then(None).otherwise(width / mid)
    tag = f"{period}_{num_std:g}"
    return df.select(
        mid.alias(f"bb_mid_{tag}"),
        upper.alias(f"bb_upper_{tag}"),
        lower.alias(f"bb_lower_{tag}"),
        pctb.alias(f"bb_pctb_{tag}"),
        bw.alias(f"bb_bandwidth_{tag}"),
    )


@register_indicator(
    name="keltner",
    category="volatility",
    requires=("high", "low", "close"),
    min_lookback=lambda p: max(int(p["period"]), int(p["atr_period"])) + 1,
    params_schema=KeltnerParams,
    multi_output=True,
    output_columns=("keltner_mid", "keltner_upper", "keltner_lower"),
)
def keltner(
    df: pl.DataFrame,
    period: int = 20,
    atr_period: int = 10,
    multiplier: float = 1.5,
) -> pl.DataFrame:
    """Keltner channel (EMA mid ± multiplier * ATR)."""
    from fmtrader.features.indicators._ops import ema_numpy

    mid = ema_numpy(df["close"].to_numpy().astype(np.float64), period)
    a = atr(df, period=atr_period).to_numpy().astype(np.float64)
    upper = mid + multiplier * a
    lower = mid - multiplier * a
    tag = f"{period}_{atr_period}_{multiplier:g}"
    warmup = max(period, atr_period) - 1
    return pl.DataFrame(
        {
            f"keltner_mid_{tag}": series_from_numpy(mid, name=f"keltner_mid_{tag}", warmup=warmup),
            f"keltner_upper_{tag}": series_from_numpy(
                upper, name=f"keltner_upper_{tag}", warmup=warmup
            ),
            f"keltner_lower_{tag}": series_from_numpy(
                lower, name=f"keltner_lower_{tag}", warmup=warmup
            ),
        }
    )


@register_indicator(
    name="donchian",
    category="volatility",
    requires=("high", "low"),
    min_lookback=lambda p: int(p["period"]),
    params_schema=PeriodParams,
    multi_output=True,
    output_columns=("donchian_high", "donchian_low"),
)
def donchian(df: pl.DataFrame, period: int = 20) -> pl.DataFrame:
    """Donchian channel high/low."""
    return pl.DataFrame(
        {
            f"donchian_high_{period}": df["high"]
            .rolling_max(period)
            .rename(f"donchian_high_{period}"),
            f"donchian_low_{period}": df["low"]
            .rolling_min(period)
            .rename(f"donchian_low_{period}"),
        }
    )


@register_indicator(
    name="chaikin_volatility",
    category="volatility",
    requires=("high", "low"),
    min_lookback=lambda p: int(p["ema_period"]) + int(p["roc_period"]),
    params_schema=ChaikinParams,
)
def chaikin_volatility(
    df: pl.DataFrame,
    ema_period: int = 10,
    roc_period: int = 10,
) -> pl.Series:
    """Chaikin volatility: ROC of EMA(high-low)."""
    from fmtrader.features.indicators._ops import ema_numpy

    hl = (df["high"] - df["low"]).to_numpy().astype(np.float64)
    e = ema_numpy(hl, ema_period)
    out = np.full_like(e, np.nan)
    for i in range(ema_period + roc_period - 1, e.shape[0]):
        prev = e[i - roc_period]
        if prev == 0 or np.isnan(prev) or np.isnan(e[i]):
            continue
        out[i] = 100.0 * (e[i] - prev) / prev
    return series_from_numpy(
        out, name=f"chaikin_vol_{ema_period}_{roc_period}", warmup=ema_period + roc_period - 2
    )


@register_indicator(
    name="parkinson",
    category="volatility",
    requires=("high", "low"),
    min_lookback=lambda p: int(p["period"]),
    params_schema=PeriodParams,
)
def parkinson(df: pl.DataFrame, period: int = 20) -> pl.Series:
    """Parkinson high-low volatility estimator (annualization omitted)."""
    # Assumes continuous trading; gold's daily break biases this slightly.
    rs = (df["high"] / df["low"]).log() ** 2
    const = 1.0 / (4.0 * np.log(2.0))
    out = (const * rs.rolling_mean(period)).sqrt()
    return df.select(out.alias(f"parkinson_{period}")).to_series()


@register_indicator(
    name="garman_klass",
    category="volatility",
    requires=("open", "high", "low", "close"),
    min_lookback=lambda p: int(p["period"]),
    params_schema=PeriodParams,
)
def garman_klass(df: pl.DataFrame, period: int = 20) -> pl.Series:
    """Garman-Klass OHLC volatility estimator."""
    log_hl = (df["high"] / df["low"]).log() ** 2
    log_co = (df["close"] / df["open"]).log() ** 2
    rs = 0.5 * log_hl - (2.0 * np.log(2.0) - 1.0) * log_co
    out = rs.rolling_mean(period).sqrt()
    return df.select(out.alias(f"garman_klass_{period}")).to_series()


@register_indicator(
    name="yang_zhang",
    category="volatility",
    requires=("open", "high", "low", "close"),
    min_lookback=lambda p: int(p["period"]) + 1,
    params_schema=PeriodParams,
)
def yang_zhang(df: pl.DataFrame, period: int = 20) -> pl.Series:
    """Yang-Zhang estimator (handles overnight gaps)."""
    open_ = df["open"].to_numpy().astype(np.float64)
    high = df["high"].to_numpy().astype(np.float64)
    low = df["low"].to_numpy().astype(np.float64)
    close = df["close"].to_numpy().astype(np.float64)
    n = close.shape[0]
    overnight = np.full(n, np.nan)
    overnight[1:] = np.log(open_[1:] / close[:-1])
    log_co = np.log(close / open_)
    log_ho = np.log(high / open_)
    log_lo = np.log(low / open_)
    rs = log_ho * (log_ho - log_co) + log_lo * (log_lo - log_co)
    k = 0.34 / (1.34 + (period + 1) / (period - 1)) if period > 1 else 0.0

    def _rolling_var(x: np.ndarray, window: int) -> np.ndarray:
        out = np.full(x.shape[0], np.nan)
        if window < 2 or x.shape[0] < window:
            return out
        c1 = np.cumsum(np.nan_to_num(x, nan=0.0))
        c2 = np.cumsum(np.nan_to_num(x, nan=0.0) ** 2)
        s1 = c1[window - 1 :] - np.concatenate([[0.0], c1[:-window]])
        s2 = c2[window - 1 :] - np.concatenate([[0.0], c2[:-window]])
        mean = s1 / window
        # population var * n/(n-1) for sample
        var = (s2 - window * mean**2) / (window - 1)
        nan_counts = np.cumsum(np.isnan(x).astype(np.float64))
        nans = nan_counts[window - 1 :] - np.concatenate([[0.0], nan_counts[:-window]])
        chunk = var.copy()
        chunk[nans > 0] = np.nan
        out[window - 1 :] = chunk
        return out

    def _rolling_mean(x: np.ndarray, window: int) -> np.ndarray:
        out = np.full(x.shape[0], np.nan)
        if window < 1 or x.shape[0] < window:
            return out
        c1 = np.cumsum(np.nan_to_num(x, nan=0.0))
        s1 = c1[window - 1 :] - np.concatenate([[0.0], c1[:-window]])
        nan_counts = np.cumsum(np.isnan(x).astype(np.float64))
        nans = nan_counts[window - 1 :] - np.concatenate([[0.0], nan_counts[:-window]])
        mean = s1 / window
        mean[nans > 0] = np.nan
        out[window - 1 :] = mean
        return out

    sigma_o = _rolling_var(overnight, period)
    sigma_c = _rolling_var(log_co, period)
    sigma_rs = _rolling_mean(rs, period)
    out = np.sqrt(np.maximum(sigma_o + k * sigma_c + (1.0 - k) * sigma_rs, 0.0))
    return series_from_numpy(out, name=f"yang_zhang_{period}", warmup=period)


@register_indicator(
    name="realized_vol",
    category="volatility",
    requires=("close",),
    min_lookback=lambda p: int(p["period"]) + 1,
    params_schema=PeriodParams,
)
def realized_vol(df: pl.DataFrame, period: int = 20) -> pl.Series:
    """Trailing std of log returns."""
    rets = df["close"].log().diff()
    out = rets.rolling_std(period, ddof=0)
    return df.select(out.alias(f"realized_vol_{period}")).to_series()
