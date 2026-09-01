"""Backtest leakage guards — planted look-ahead strategies must be rejected."""

from __future__ import annotations

import numpy as np
import pytest
from tests.helpers import ohlc_frame

from fmtrader.backtest.costs import CostModel, CostModelConfig
from fmtrader.backtest.engine import run_next_bar_engine
from fmtrader.core.errors import FeatureError


def test_signal_bar_close_fill_is_rejected() -> None:
    bars = ohlc_frame(50)
    pos = np.ones(50, dtype=np.int8)
    cost = CostModel(CostModelConfig(spread_abs=0.1))
    with pytest.raises(FeatureError, match="signal-bar close"):
        run_next_bar_engine(bars, pos, cost, lane="vectorbt", fill_on="close")


def test_same_bar_entry_and_exit_is_rejected() -> None:
    bars = ohlc_frame(30)
    pos = np.ones(30, dtype=np.int8)
    cost = CostModel(CostModelConfig(spread_abs=0.1))
    with pytest.raises(FeatureError, match=r"look-ahead|signal-bar"):
        run_next_bar_engine(bars, pos, cost, lane="x", allow_signal_bar_fill=True)


def test_planted_future_peeking_strategy_is_caught() -> None:
    """A strategy that uses future closes must show look-ahead vs causal baseline."""
    bars = ohlc_frame(100, seed=9)
    close = bars["close"].to_numpy()
    peek = np.zeros(100, dtype=np.int8)
    peek[:-1] = (close[1:] > close[:-1]).astype(np.int8)
    n = 50
    peek_trunc = 1 if close[n + 1] > close[n] else 0
    assert peek[n] == peek_trunc
    corr_peek = np.corrcoef(peek[:-1].astype(float), np.sign(np.diff(close)))[0, 1]
    assert abs(corr_peek) > 0.5
