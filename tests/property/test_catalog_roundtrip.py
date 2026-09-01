"""Catalog round-trip property tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
from hypothesis import given, settings
from hypothesis import strategies as st

from fmtrader.data.catalog import Catalog, content_hash_frame


def _tiny_frame(n: int = 5) -> pl.DataFrame:
    t0 = datetime(2021, 1, 4, 12, 0, tzinfo=UTC)
    return pl.DataFrame(
        {
            "ts": [t0 + timedelta(minutes=i) for i in range(n)],
            "symbol": ["XAUUSD"] * n,
            "instrument_class": ["spot_cfd"] * n,
            "timeframe": ["1m"] * n,
            "open": [100.0 + i for i in range(n)],
            "high": [101.0 + i for i in range(n)],
            "low": [99.0 + i for i in range(n)],
            "close": [100.5 + i for i in range(n)],
            "volume": [None] * n,
            "open_interest": [None] * n,
            "bid": [100.5 + i for i in range(n)],
            "ask": [None] * n,
            "is_tradable": [True] * n,
        }
    )


def test_write_read_frame_equality(tmp_path: Path) -> None:
    frame = _tiny_frame(12)
    cat = Catalog(tmp_path / "catalog")
    cat.write(frame, symbol="XAUUSD", timeframe="1m")
    back = cat.read(symbol="XAUUSD", timeframe="1m")
    assert back.select(frame.columns).sort("ts").equals(frame.sort("ts"))


def test_content_hash_stable_across_writes() -> None:
    frame = _tiny_frame(8)
    assert content_hash_frame(frame) == content_hash_frame(frame)


def test_content_hash_changes_when_data_changes() -> None:
    a = _tiny_frame(8)
    b = a.with_columns(pl.col("close") + 1.0)
    assert content_hash_frame(a) != content_hash_frame(b)


@given(st.integers(min_value=1, max_value=40))
@settings(max_examples=10, deadline=None)
def test_write_read_frame_equality_hypothesis(n: int) -> None:
    import tempfile

    frame = _tiny_frame(n)
    with tempfile.TemporaryDirectory() as td:
        cat = Catalog(Path(td) / "catalog")
        cat.write(frame, symbol="XAUUSD", timeframe="1m")
        back = cat.read(symbol="XAUUSD", timeframe="1m")
        assert back.height == frame.height
        assert back["close"].to_list() == frame["close"].to_list()
