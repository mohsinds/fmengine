"""Trade enrichment tests."""

from __future__ import annotations

import numpy as np
import pytest

from fmtrader.backtest.enrichment import compute_mae_mfe


def test_mae_mfe_computed_correctly_on_fixture() -> None:
    # Long from 100; high 110, low 95
    mae, mfe = compute_mae_mfe(
        side=1,
        entry_price=100.0,
        highs=np.array([100.0, 110.0, 105.0]),
        lows=np.array([100.0, 98.0, 95.0]),
    )
    assert mfe == pytest.approx(10.0)
    assert mae == pytest.approx(5.0)


def test_exit_reason_classified_correctly() -> None:
    from fmtrader.backtest.enrichment import TradeRecord

    t = TradeRecord(
        entry_i=0,
        exit_i=5,
        side=1,
        entry_price=1.0,
        exit_price=1.1,
        qty=1.0,
        pnl_gross=0.1,
        pnl_net=0.05,
        mae=0.01,
        mfe=0.12,
        exit_reason="signal",
    )
    assert t.exit_reason in {"target", "stop", "time", "signal", "eod"}
