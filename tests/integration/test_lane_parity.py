"""Lane parity integration tests (shared next-bar fill model)."""

from __future__ import annotations

import numpy as np
import pytest

from fmtrader.backtest.costs import CostModel, CostModelConfig
from fmtrader.backtest.nautilus.runner import run_nautilus_lane
from fmtrader.backtest.vbt.runner import run_vectorbt_lane
from fmtrader.strategy.library.buy_and_hold import BuyAndHold
from fmtrader.strategy.library.ema_cross import EmaCross
from tests.helpers import ohlc_frame

pytestmark = pytest.mark.integration


def test_buy_and_hold_net_return_matches_across_lanes() -> None:
    bars = ohlc_frame(500, seed=1).with_columns(__import__("polars").lit(True).alias("is_tradable"))
    pos = BuyAndHold().generate(bars, {}).to_numpy()
    cost = CostModel(CostModelConfig(spread_abs=0.2, slippage_base_abs=0.01, commission_bps=0.5))
    a = run_vectorbt_lane(bars, pos, cost)
    b = run_nautilus_lane(bars, pos, cost)
    assert a.metrics_net.total_return_net == pytest.approx(b.metrics_net.total_return_net, abs=1e-9)
    assert a.metrics_net.cost_drag_pct == pytest.approx(b.metrics_net.cost_drag_pct, abs=1e-6)


def test_simple_ema_cross_trade_count_matches_across_lanes() -> None:
    bars = ohlc_frame(800, seed=2).with_columns(__import__("polars").lit(True).alias("is_tradable"))
    pos = EmaCross().generate(bars, {"fast": 5, "slow": 20}).to_numpy()
    cost = CostModel(CostModelConfig(spread_abs=0.1))
    a = run_vectorbt_lane(bars, pos, cost)
    b = run_nautilus_lane(bars, pos, cost)
    assert a.metrics_net.trade_count == b.metrics_net.trade_count


def test_trade_directions_match_across_lanes() -> None:
    bars = ohlc_frame(600, seed=3).with_columns(__import__("polars").lit(True).alias("is_tradable"))
    pos = EmaCross().generate(bars, {"fast": 8, "slow": 21}).to_numpy()
    cost = CostModel(CostModelConfig(spread_abs=0.15))
    a = run_vectorbt_lane(bars, pos, cost)
    b = run_nautilus_lane(bars, pos, cost)
    assert [t.side for t in a.trades] == [t.side for t in b.trades]
    assert np.allclose(a.position, b.position)
