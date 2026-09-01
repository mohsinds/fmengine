"""Dukascopy adapter tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from fmtrader.core.enums import InstrumentClass, Side
from fmtrader.core.errors import AdapterError
from fmtrader.data.adapters.dukascopy import DukascopyAdapter


def _write_csv(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_epoch_ms_parsed_as_milliseconds_not_seconds(tmp_path: Path) -> None:
    # 1609632000000 ms = 2021-01-03 00:00:00 UTC — if read as seconds → year 52984
    csv = _write_csv(
        tmp_path / "sample.csv",
        "timestamp,open,high,low,close\n1609632000000,1909.718,1909.718,1909.718,1909.718\n",
    )
    result = DukascopyAdapter().read(
        csv,
        symbol="XAUUSD",
        timeframe="1m",
        instrument_class=InstrumentClass.SPOT_CFD,
        side=Side.BID,
    )
    ts = result.frame["ts"][0]
    assert ts.year == 2021
    assert ts.month == 1
    assert ts.day == 3


def test_capabilities_declare_no_volume_no_spread() -> None:
    caps = DukascopyAdapter().capabilities()
    assert caps.has_volume is False
    assert caps.has_spread is False
    assert caps.has_open_interest is False


def test_missing_column_raises_named_error(tmp_path: Path) -> None:
    csv = _write_csv(
        tmp_path / "bad.csv",
        "timestamp,open,high,close\n1609632000000,1,1,1\n",
    )
    with pytest.raises(AdapterError, match="low"):
        DukascopyAdapter().read(
            csv,
            symbol="XAUUSD",
            timeframe="1m",
            instrument_class=InstrumentClass.SPOT_CFD,
            side=Side.BID,
        )
