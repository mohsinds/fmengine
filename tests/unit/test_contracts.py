"""Bar contract unit tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fmtrader.core.contracts import Bar
from fmtrader.core.enums import InstrumentClass
from fmtrader.core.errors import ContractError


def test_bar_rejects_naive_datetime() -> None:
    with pytest.raises(ContractError, match="timezone-aware"):
        Bar(
            ts=datetime(2021, 1, 1, 0, 0, 0),
            symbol="XAUUSD",
            instrument_class=InstrumentClass.SPOT_CFD,
            timeframe="1m",
            open=1.0,
            high=1.0,
            low=1.0,
            close=1.0,
        )


def test_bar_rejects_ohlc_violation() -> None:
    with pytest.raises(ContractError, match="OHLC"):
        Bar(
            ts=datetime(2021, 1, 1, 0, 0, 0, tzinfo=UTC),
            symbol="XAUUSD",
            instrument_class=InstrumentClass.SPOT_CFD,
            timeframe="1m",
            open=10.0,
            high=9.0,  # high < open
            low=8.0,
            close=9.5,
        )


def test_optional_fields_are_none_not_zero() -> None:
    bar = Bar(
        ts=datetime(2021, 1, 1, 0, 0, 0, tzinfo=UTC),
        symbol="XAUUSD",
        instrument_class=InstrumentClass.SPOT_CFD,
        timeframe="1m",
        open=1909.0,
        high=1910.0,
        low=1908.0,
        close=1909.5,
    )
    assert bar.volume is None
    assert bar.open_interest is None
    assert bar.bid is None
    assert bar.ask is None
