"""Microstructure indicators — registered but gated until CME depth data."""

from __future__ import annotations

import polars as pl
from pydantic import BaseModel, Field

from fmtrader.core.errors import FeatureError
from fmtrader.features.registry import register_indicator


class PeriodParams(BaseModel):
    period: int = Field(default=20, ge=1)


@register_indicator(
    name="order_book_imbalance",
    category="microstructure",
    requires=("bid", "ask"),
    requires_spread=True,
    min_lookback=1,
    params_schema=PeriodParams,
)
def order_book_imbalance(df: pl.DataFrame, period: int = 20) -> pl.Series:
    """Placeholder — requires L2 depth not present in Phase 1-3 datasets."""
    raise FeatureError(
        "order_book_imbalance requires L2 depth; not available until CME phase "
        f"(period={period}, rows={df.height})"
    )


@register_indicator(
    name="hawkes_intensity",
    category="microstructure",
    requires=("ts",),
    requires_volume=True,
    min_lookback=lambda p: int(p["period"]),
    params_schema=PeriodParams,
)
def hawkes_intensity(df: pl.DataFrame, period: int = 20) -> pl.Series:
    """Placeholder — trade-arrival Hawkes intensity needs tick data."""
    raise FeatureError(
        "hawkes_intensity requires tick arrivals; not available until CME phase "
        f"(period={period}, rows={df.height})"
    )
