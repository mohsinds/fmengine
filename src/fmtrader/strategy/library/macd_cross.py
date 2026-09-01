"""MACD crossover strategy — long when MACD line > signal."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import polars as pl
from pydantic import BaseModel, Field

from fmtrader.features.indicators.momentum import macd
from fmtrader.strategy.base import register_strategy
from fmtrader.strategy.library._util import apply_tradable_hold


class MacdCrossParams(BaseModel):
    fast: int = Field(default=12, ge=1)
    slow: int = Field(default=26, ge=2)
    signal: int = Field(default=9, ge=1)


@register_strategy
class MacdCross:
    name = "macd_cross"
    params_schema = MacdCrossParams

    def generate(self, bars: pl.DataFrame, params: Mapping[str, Any]) -> pl.Series:
        p = MacdCrossParams(**params)
        if p.fast >= p.slow:
            raise ValueError("macd_cross requires fast < slow")
        frame = macd(bars, fast=p.fast, slow=p.slow, signal=p.signal)
        line = frame[f"macd_{p.fast}_{p.slow}"].to_numpy()
        sig = frame[f"macd_signal_{p.fast}_{p.slow}_{p.signal}"].to_numpy()
        long_sig = (line > sig) & np.isfinite(line) & np.isfinite(sig)
        pos = np.where(long_sig, 1, 0).astype(np.int8)
        pos = apply_tradable_hold(pos, bars)
        return pl.Series("position", pos)
