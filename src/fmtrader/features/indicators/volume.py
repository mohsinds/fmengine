"""Volume indicators — gated off when dataset has_volume=false."""

from __future__ import annotations

import polars as pl
from pydantic import BaseModel, Field

from fmtrader.features.registry import register_indicator


class PeriodParams(BaseModel):
    period: int = Field(default=20, ge=1)


class EmptyParams(BaseModel):
    pass


@register_indicator(
    name="vwap",
    category="volume",
    requires=("high", "low", "close", "volume"),
    requires_volume=True,
    min_lookback=lambda p: int(p["period"]),
    params_schema=PeriodParams,
)
def vwap(df: pl.DataFrame, period: int = 20) -> pl.Series:
    """Trailing VWAP over ``period`` bars."""
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    num = (tp * df["volume"]).rolling_sum(period)
    den = df["volume"].rolling_sum(period)
    out = num / den
    return df.select(out.alias(f"vwap_{period}")).to_series()


@register_indicator(
    name="obv",
    category="volume",
    requires=("close", "volume"),
    requires_volume=True,
    min_lookback=2,
    params_schema=EmptyParams,
)
def obv(df: pl.DataFrame) -> pl.Series:
    """On-balance volume."""
    direction = df["close"].diff().sign().fill_null(0)
    return df.select((direction * df["volume"]).cum_sum().alias("obv")).to_series()


@register_indicator(
    name="mfi",
    category="volume",
    requires=("high", "low", "close", "volume"),
    requires_volume=True,
    min_lookback=lambda p: int(p["period"]) + 1,
    params_schema=PeriodParams,
)
def mfi(df: pl.DataFrame, period: int = 14) -> pl.Series:
    """Money Flow Index."""
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    mf = tp * df["volume"]
    delta = tp.diff()
    pos = pl.when(delta > 0).then(mf).otherwise(0.0).rolling_sum(period)
    neg = pl.when(delta < 0).then(mf).otherwise(0.0).rolling_sum(period)
    ratio = pos / neg
    out = pl.when(neg == 0).then(100.0).otherwise(100.0 - (100.0 / (1.0 + ratio)))
    return df.select(out.alias(f"mfi_{period}")).to_series()
