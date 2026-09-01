"""Buy-and-hold strategy — long from first tradable bar."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import polars as pl

from fmtrader.strategy.base import EmptyParams, register_strategy


@register_strategy
class BuyAndHold:
    name = "buy_and_hold"
    params_schema = EmptyParams

    def generate(self, bars: pl.DataFrame, params: Mapping[str, Any]) -> pl.Series:
        _ = params
        n = bars.height
        pos = [0] * n
        if "is_tradable" in bars.columns:
            tradable = bars["is_tradable"].to_list()
            started = False
            for i, ok in enumerate(tradable):
                if ok or started:
                    # once we enter, stay long (including non-tradable flats)
                    if ok and not started:
                        started = True
                    if started:
                        pos[i] = 1
        else:
            pos = [1] * n
        return pl.Series("position", pos, dtype=pl.Int8)
