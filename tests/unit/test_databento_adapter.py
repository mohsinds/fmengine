"""Databento adapter unit tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fmtrader.core.enums import InstrumentClass
from fmtrader.core.errors import AdapterError
from fmtrader.data.adapters.databento import DatabentoAdapter, parse_cme_symbol


def test_capabilities_declare_volume_and_open_interest() -> None:
    caps = DatabentoAdapter().capabilities()
    assert caps.has_volume is True
    assert caps.has_open_interest is True
    assert caps.has_spread is False
    assert caps.has_depth is False
    assert caps.session_calendar == "comex_metals"
    assert caps.source == "databento"


@pytest.mark.parametrize(
    ("symbol", "root", "month", "year"),
    [
        ("GCZ5", "GC", 12, 2025),
        ("GCZ25", "GC", 12, 2025),
        ("GCG26", "GC", 2, 2026),
        ("MGCZ2025", "MGC", 12, 2025),
        ("gcz25", "GC", 12, 2025),
    ],
)
def test_contract_symbol_parsed_to_root_month_year(
    symbol: str, root: str, month: int, year: int
) -> None:
    p = parse_cme_symbol(symbol)
    assert p.root == root
    assert p.month == month
    assert p.year == year


def test_invalid_symbol_raises() -> None:
    with pytest.raises(AdapterError, match="Unrecognized"):
        parse_cme_symbol("XAUUSD")


def test_read_csv_with_volume_and_oi(tmp_path: Path) -> None:
    t0 = datetime(2024, 1, 2, 15, 0, tzinfo=UTC)
    lines = ["timestamp,open,high,low,close,volume,open_interest"]
    for i in range(5):
        ts = int((t0 + timedelta(minutes=i)).timestamp() * 1000)
        px = 2000.0 + i
        lines.append(f"{ts},{px},{px + 1},{px - 1},{px},{100 + i},{1000 + i}")
    path = tmp_path / "gcz25.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = DatabentoAdapter().read(
        path,
        symbol="GCZ25",
        timeframe="1m",
        instrument_class=InstrumentClass.FUTURES_RAW,
    )
    assert result.frame.height == 5
    assert result.capabilities.has_volume is True
    assert result.frame["volume"].null_count() == 0
    assert result.frame["open_interest"].null_count() == 0
    assert float(result.frame["volume"][0]) == 100.0
