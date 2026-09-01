"""Funnel consistency tests."""

from __future__ import annotations

import pytest

from fmtrader.backtest.funnel import Funnel


def test_funnel_counts_are_monotonically_non_increasing() -> None:
    f = Funnel()
    f.set_count("raw_signals", 10)
    f.set_count("after_regime", 8)
    f.set_count("after_gate", 7)
    f.set_count("after_risk", 6)
    f.set_count("orders", 5)
    f.set_count("fills", 5)
    f.add_drop("after_regime", "non_tradable", 2)
    f.add_drop("after_gate", "gate", 1)
    f.add_drop("after_risk", "risk", 1)
    f.add_drop("orders", "shift", 1)
    f.validate()


def test_drop_reasons_sum_to_difference_between_stages() -> None:
    f = Funnel()
    f.set_count("raw_signals", 10)
    f.set_count("after_regime", 7)
    f.set_count("after_gate", 7)
    f.set_count("after_risk", 7)
    f.set_count("orders", 7)
    f.set_count("fills", 7)
    f.add_drop("after_regime", "x", 3)
    f.validate()
    with pytest.raises(ValueError):
        bad = Funnel()
        bad.set_count("raw_signals", 5)
        bad.set_count("after_regime", 10)
        bad.validate()
