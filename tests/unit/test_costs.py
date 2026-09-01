"""Cost model unit tests."""

from __future__ import annotations

import pytest

from fmtrader.backtest.costs import (
    CostModel,
    CostModelConfig,
    validate_cost_config_for_dataset,
)
from fmtrader.core.errors import FeatureError


def test_spread_applied_both_sides_of_round_trip() -> None:
    cfg = CostModelConfig(spread_abs=2.0, slippage_base_abs=0.0, commission_per_side=0.0)
    m = CostModel(cfg)
    buy_px, b = m.one_way(price=100.0, side="buy")
    sell_px, s = m.one_way(price=100.0, side="sell")
    assert buy_px == pytest.approx(101.0)
    assert sell_px == pytest.approx(99.0)
    assert b.spread_half + s.spread_half == pytest.approx(2.0)


def test_session_multiplier_widens_offhours_spread() -> None:
    cfg = CostModelConfig(spread_abs=1.0, offsession_spread_mult=2.0)
    m = CostModel(cfg)
    _, on = m.one_way(price=100.0, side="buy", in_session=True)
    _, off = m.one_way(price=100.0, side="buy", in_session=False)
    assert off.spread_half == pytest.approx(on.spread_half * 2.0)


def test_slippage_scales_with_volatility() -> None:
    cfg = CostModelConfig(spread_abs=0.1, slippage_base_abs=0.0, slippage_vol_mult=0.5)
    m = CostModel(cfg)
    px0, _ = m.one_way(price=100.0, side="buy", vol_proxy=0.0)
    px1, _ = m.one_way(price=100.0, side="buy", vol_proxy=2.0)
    assert px1 - px0 == pytest.approx(1.0)


def test_zero_cost_config_rejected_when_spread_unmeasured() -> None:
    cfg = CostModelConfig(spread_abs=0.0)
    with pytest.raises(FeatureError, match="has_spread=false"):
        validate_cost_config_for_dataset(cfg, has_spread=False, dataset_id="xauusd_test")
