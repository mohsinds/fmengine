"""Unit tests for indicator-based strategies."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from fmtrader.strategy.base import get_strategy, list_strategies
from fmtrader.strategy.library import (  # noqa: F401 — register
    bollinger_breakout,
    ema_cross,
    macd_cross,
    rsi_mean_reversion,
    supertrend_trend,
)


def _bars(n: int = 200, seed: int = 0) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    close = 2000.0 + np.cumsum(rng.normal(0, 0.5, n))
    high = close + rng.uniform(0.1, 1.0, n)
    low = close - rng.uniform(0.1, 1.0, n)
    open_ = close + rng.normal(0, 0.2, n)
    ts = [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(minutes=i) for i in range(n)]
    return pl.DataFrame(
        {
            "ts": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "is_tradable": [True] * n,
        }
    )


@pytest.mark.parametrize(
    "name,params",
    [
        ("ema_cross", {"fast": 8, "slow": 21}),
        ("rsi_mean_reversion", {"period": 14, "oversold": 30, "overbought": 70}),
        ("macd_cross", {"fast": 12, "slow": 26, "signal": 9}),
        ("bollinger_breakout", {"period": 20, "num_std": 2.0}),
        ("supertrend_trend", {"period": 10, "multiplier": 3.0}),
    ],
)
def test_strategy_emits_position(name: str, params: dict) -> None:
    assert name in list_strategies()
    bars = _bars()
    pos = get_strategy(name).generate(bars, params)
    assert len(pos) == bars.height
    assert set(np.unique(pos.to_numpy())).issubset({-1, 0, 1})


def test_rsi_requires_oversold_lt_overbought() -> None:
    with pytest.raises(ValueError):
        get_strategy("rsi_mean_reversion").generate(
            _bars(), {"period": 14, "oversold": 70, "overbought": 30}
        )
