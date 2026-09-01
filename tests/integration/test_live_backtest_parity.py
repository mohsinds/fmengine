"""Live/paper vs backtest strategy code-path parity."""

from __future__ import annotations

import numpy as np
import pytest

from fmtrader.execution.broker.ibkr import IBKRPaperBroker
from fmtrader.execution.runtime import (
    ExecutionRuntime,
    RuntimeConfig,
    signal_sequence_from_strategy,
)
from fmtrader.strategy.library.buy_and_hold import BuyAndHold
from fmtrader.strategy.library.ema_cross import EmaCross
from tests.helpers import ohlc_frame

pytestmark = pytest.mark.integration


def test_same_strategy_code_path_in_both_modes() -> None:
    bars = ohlc_frame(200, seed=7).with_columns(__import__("polars").lit(True).alias("is_tradable"))
    strategy = EmaCross()
    params = {"fast": 5, "slow": 20}

    # Backtest mode (no broker fills) — same generate()
    bt = ExecutionRuntime(
        strategy=strategy,
        config=RuntimeConfig(
            symbol="XAUUSD",
            strategy_name="ema_cross",
            params=params,
            mode="backtest",
        ),
        broker=None,
    )
    bt_result = bt.run(bars)

    # Paper mode — same strategy instance class path
    broker = IBKRPaperBroker()
    paper = ExecutionRuntime(
        strategy=EmaCross(),
        config=RuntimeConfig(
            symbol="XAUUSD",
            strategy_name="ema_cross",
            params=params,
            mode="paper",
            default_qty=1.0,
        ),
        broker=broker,
    )
    paper_result = paper.run(bars)

    assert bt_result.desired_positions == paper_result.desired_positions
    assert signal_sequence_from_strategy(strategy, bars, params).tolist() == (
        bt_result.desired_positions
    )


def test_signal_sequence_matches_replayed_backtest() -> None:
    bars = ohlc_frame(300, seed=11).with_columns(
        __import__("polars").lit(True).alias("is_tradable")
    )
    strategy = BuyAndHold()
    params: dict = {}
    expected = signal_sequence_from_strategy(strategy, bars, params)

    broker = IBKRPaperBroker()
    runtime = ExecutionRuntime(
        strategy=BuyAndHold(),
        config=RuntimeConfig(
            symbol="XAUUSD",
            strategy_name="buy_and_hold",
            params=params,
            mode="paper",
        ),
        broker=broker,
    )
    result = runtime.run(bars)
    assert np.array_equal(np.asarray(result.desired_positions, dtype=np.int8), expected)
    # Buy-and-hold should produce at least one fill on first long
    assert result.fills >= 1
