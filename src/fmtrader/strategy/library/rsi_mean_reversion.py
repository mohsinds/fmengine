"""RSI mean-reversion strategy — long when oversold, flat when overbought."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import polars as pl
from pydantic import BaseModel, Field

from fmtrader.features.indicators.momentum import rsi
from fmtrader.strategy.base import register_strategy
from fmtrader.strategy.library._util import apply_tradable_hold


class RsiMeanReversionParams(BaseModel):
    period: int = Field(default=14, ge=2)
    oversold: float = Field(default=30.0, ge=1.0, le=50.0)
    overbought: float = Field(default=70.0, ge=50.0, le=99.0)


@register_strategy
class RsiMeanReversion:
    name = "rsi_mean_reversion"
    params_schema = RsiMeanReversionParams

    def generate(self, bars: pl.DataFrame, params: Mapping[str, Any]) -> pl.Series:
        p = RsiMeanReversionParams(**params)
        if p.oversold >= p.overbought:
            raise ValueError("rsi_mean_reversion requires oversold < overbought")
        r = rsi(bars, period=p.period).to_numpy()
        n = len(r)
        pos = np.zeros(n, dtype=np.int8)
        state = 0
        for i in range(n):
            if not np.isfinite(r[i]):
                pos[i] = state
                continue
            if r[i] <= p.oversold:
                state = 1
            elif r[i] >= p.overbought:
                state = 0
            pos[i] = state
        pos = apply_tradable_hold(pos, bars)
        return pl.Series("position", pos)
