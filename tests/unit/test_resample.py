"""Resample unit tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl

from fmtrader.data.calendars import XAUUSD_FX
from fmtrader.data.resample import resample_ohlc


def test_1m_to_5m_ohlc_aggregation_correct() -> None:
    t0 = datetime(2021, 1, 4, 12, 0, tzinfo=UTC)
    rows = []
    for i in range(5):
        o = 100.0 + i
        rows.append(
            {
                "ts": t0 + timedelta(minutes=i),
                "symbol": "XAUUSD",
                "instrument_class": "spot_cfd",
                "timeframe": "1m",
                "open": o,
                "high": o + 1,
                "low": o - 1,
                "close": o + 0.5,
                "volume": None,
                "open_interest": None,
                "bid": None,
                "ask": None,
                "is_tradable": True,
            }
        )
    frame = pl.DataFrame(rows)
    out = resample_ohlc(frame, target_timeframe="5m", calendar=XAUUSD_FX)
    assert out.height == 1
    assert out["open"][0] == 100.0
    assert out["close"][0] == 104.5
    assert out["high"][0] == 105.0
    assert out["low"][0] == 99.0
    assert out["timeframe"][0] == "5m"


def test_resample_respects_session_boundaries() -> None:
    # Include a Saturday bar that should be dropped before aggregation
    sat = datetime(2021, 1, 9, 12, 0, tzinfo=UTC)
    mon = datetime(2021, 1, 4, 12, 0, tzinfo=UTC)
    rows = []
    for i in range(5):
        rows.append(
            {
                "ts": mon + timedelta(minutes=i),
                "symbol": "XAUUSD",
                "instrument_class": "spot_cfd",
                "timeframe": "1m",
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "volume": None,
                "open_interest": None,
                "bid": None,
                "ask": None,
                "is_tradable": True,
            }
        )
    rows.append(
        {
            "ts": sat,
            "symbol": "XAUUSD",
            "instrument_class": "spot_cfd",
            "timeframe": "1m",
            "open": 9.0,
            "high": 9.0,
            "low": 9.0,
            "close": 9.0,
            "volume": None,
            "open_interest": None,
            "bid": None,
            "ask": None,
            "is_tradable": False,
        }
    )
    frame = pl.DataFrame(rows)
    out = resample_ohlc(frame, target_timeframe="5m", calendar=XAUUSD_FX)
    assert out.height == 1
    assert out["open"][0] == 1.0


def test_resample_never_creates_bars_from_gaps() -> None:
    t0 = datetime(2021, 1, 4, 12, 0, tzinfo=UTC)
    t1 = t0 + timedelta(minutes=60)
    frame = pl.DataFrame(
        {
            "ts": [t0, t1],
            "symbol": ["XAUUSD", "XAUUSD"],
            "instrument_class": ["spot_cfd", "spot_cfd"],
            "timeframe": ["1m", "1m"],
            "open": [1.0, 2.0],
            "high": [1.0, 2.0],
            "low": [1.0, 2.0],
            "close": [1.0, 2.0],
            "volume": [None, None],
            "open_interest": [None, None],
            "bid": [None, None],
            "ask": [None, None],
            "is_tradable": [True, True],
        }
    )
    out = resample_ohlc(frame, target_timeframe="5m", calendar=XAUUSD_FX)
    # Only buckets that contain source bars
    assert out.height == 2
