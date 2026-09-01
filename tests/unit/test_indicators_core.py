"""Trend / momentum / volatility / session indicator unit tests."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

import fmtrader.features  # noqa: F401
from fmtrader.features.indicators.momentum import rsi
from fmtrader.features.indicators.session import minute_of_day
from fmtrader.features.indicators.trend import sma
from fmtrader.features.indicators.volatility import atr, bollinger, donchian
from fmtrader.features.registry import compute_indicator
from tests.helpers import assert_no_lookahead, constant_ohlc, ohlc_frame


def test_sma_matches_reference_values() -> None:
    df = pl.DataFrame({"close": [1.0, 2.0, 3.0, 4.0, 5.0]})
    out = sma(df, period=3)
    assert out[0] is None and out[1] is None
    assert out[2] == pytest.approx(2.0)
    assert out[4] == pytest.approx(4.0)


def test_sma_warmup_null_count_equals_min_lookback() -> None:
    df = ohlc_frame(30)
    out = sma(df, period=10)
    assert sum(1 for v in out if v is None) == 9


def test_sma_no_lookahead() -> None:
    df = ohlc_frame(80)
    assert_no_lookahead(lambda d: sma(d, period=10), df, index=40)


def test_sma_handles_constant_series() -> None:
    out = sma(constant_ohlc(30), period=5)
    assert out[10] == pytest.approx(100.0)


def test_sma_handles_single_row() -> None:
    df = ohlc_frame(1)
    from fmtrader.core.errors import FeatureError

    with pytest.raises(FeatureError, match="min_lookback"):
        compute_indicator("sma", df, period=5)


def test_rsi_matches_hand_computed_short() -> None:
    # Monotonic up → RSI near 100 after warmup
    close = np.linspace(100, 110, 30)
    df = ohlc_frame(30).with_columns(pl.Series("close", close))
    out = rsi(df, period=14)
    assert out[20] is not None
    assert float(out[20]) > 70.0


def test_rsi_no_lookahead() -> None:
    df = ohlc_frame(100)
    assert_no_lookahead(lambda d: rsi(d, period=14), df, index=50)


def test_atr_non_negative_on_fixture() -> None:
    out = atr(ohlc_frame(100), period=14)
    vals = [float(v) for v in out if v is not None]
    assert vals and min(vals) >= 0.0


def test_atr_no_lookahead() -> None:
    df = ohlc_frame(100)
    assert_no_lookahead(lambda d: atr(d, period=14), df, index=60)


def test_bollinger_ordering() -> None:
    bb = bollinger(ohlc_frame(100), period=20, num_std=2.0)
    for i in range(30, 80):
        lo = bb["bb_lower_20_2"][i]
        mid = bb["bb_mid_20_2"][i]
        up = bb["bb_upper_20_2"][i]
        if None in (lo, mid, up):
            continue
        assert float(lo) <= float(mid) <= float(up)


def test_donchian_contains_close() -> None:
    df = ohlc_frame(80)
    d = donchian(df, period=20)
    for i in range(30, 70):
        hi = d["donchian_high_20"][i]
        lo = d["donchian_low_20"][i]
        c = df["close"][i]
        assert float(lo) <= float(c) <= float(hi)


def test_minute_of_day_no_i8_overflow() -> None:
    df = ohlc_frame(1).with_columns(pl.datetime(2021, 1, 4, 21, 30, time_zone="UTC").alias("ts"))
    assert minute_of_day(df)[0] == 21 * 60 + 30
