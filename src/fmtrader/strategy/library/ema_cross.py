"""EMA crossover strategy."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import polars as pl
from pydantic import BaseModel, Field

from fmtrader.features.indicators.trend import ema
from fmtrader.strategy.base import register_strategy


class EmaCrossParams(BaseModel):
    fast: int = Field(default=12, ge=1)
    slow: int = Field(default=26, ge=2)


@register_strategy
class EmaCross:
    name = "ema_cross"
    params_schema = EmaCrossParams

    def generate(self, bars: pl.DataFrame, params: Mapping[str, Any]) -> pl.Series:
        p = EmaCrossParams(**params)
        if p.fast >= p.slow:
            raise ValueError("ema_cross requires fast < slow")
        fast = ema(bars, period=p.fast).to_numpy()
        slow = ema(bars, period=p.slow).to_numpy()
        long_sig = (fast > slow) & np.isfinite(fast) & np.isfinite(slow)
        pos = np.where(long_sig, 1, 0).astype(np.int8)
        if "is_tradable" in bars.columns:
            tradable = bars["is_tradable"].to_numpy()
            # Do not open/flip on non-tradable bars — hold prior desired
            for i in range(len(pos)):
                if not tradable[i]:
                    pos[i] = pos[i - 1] if i else 0
        return pl.Series("position", pos)
