"""Supertrend trend-follow — long when close above Supertrend line."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import polars as pl
from pydantic import BaseModel, Field

from fmtrader.features.indicators.trend import supertrend
from fmtrader.strategy.base import register_strategy
from fmtrader.strategy.library._util import apply_tradable_hold


class SupertrendTrendParams(BaseModel):
    period: int = Field(default=10, ge=2)
    multiplier: float = Field(default=3.0, gt=0.0)


@register_strategy
class SupertrendTrend:
    name = "supertrend_trend"
    params_schema = SupertrendTrendParams

    def generate(self, bars: pl.DataFrame, params: Mapping[str, Any]) -> pl.Series:
        p = SupertrendTrendParams(**params)
        st = supertrend(bars, period=p.period, multiplier=p.multiplier).to_numpy()
        close = bars["close"].to_numpy()
        long_sig = (close > st) & np.isfinite(st)
        pos = np.where(long_sig, 1, 0).astype(np.int8)
        pos = apply_tradable_hold(pos, bars)
        return pl.Series("position", pos)
