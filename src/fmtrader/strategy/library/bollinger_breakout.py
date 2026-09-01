"""Bollinger breakout — long above upper band, flat below mid."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import polars as pl
from pydantic import BaseModel, Field

from fmtrader.features.indicators.volatility import bollinger
from fmtrader.strategy.base import register_strategy
from fmtrader.strategy.library._util import apply_tradable_hold


class BollingerBreakoutParams(BaseModel):
    period: int = Field(default=20, ge=2)
    num_std: float = Field(default=2.0, gt=0.0)


@register_strategy
class BollingerBreakout:
    name = "bollinger_breakout"
    params_schema = BollingerBreakoutParams

    def generate(self, bars: pl.DataFrame, params: Mapping[str, Any]) -> pl.Series:
        p = BollingerBreakoutParams(**params)
        frame = bollinger(bars, period=p.period, num_std=p.num_std)
        tag = f"{p.period}_{p.num_std:g}"
        upper = frame[f"bb_upper_{tag}"].to_numpy()
        mid = frame[f"bb_mid_{tag}"].to_numpy()
        close = bars["close"].to_numpy()
        n = len(close)
        pos = np.zeros(n, dtype=np.int8)
        state = 0
        for i in range(n):
            if not (np.isfinite(upper[i]) and np.isfinite(mid[i])):
                pos[i] = state
                continue
            if close[i] > upper[i]:
                state = 1
            elif close[i] < mid[i]:
                state = 0
            pos[i] = state
        pos = apply_tradable_hold(pos, bars)
        return pl.Series("position", pos)
