"""Property tests for indicator invariants."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

import fmtrader.features  # noqa: F401
from fmtrader.features.indicators.momentum import rsi
from fmtrader.features.indicators.volatility import atr, bollinger, donchian
from tests.helpers import ohlc_frame


@given(seed=st.integers(0, 10_000), n=st.integers(80, 150))
@settings(max_examples=20, deadline=None)
def test_rsi_bounded_0_100(seed: int, n: int) -> None:
    out = rsi(ohlc_frame(n, seed=seed), period=14)
    for v in out:
        if v is None:
            continue
        assert 0.0 <= float(v) <= 100.0


@given(seed=st.integers(0, 10_000), n=st.integers(80, 150))
@settings(max_examples=20, deadline=None)
def test_atr_non_negative(seed: int, n: int) -> None:
    out = atr(ohlc_frame(n, seed=seed), period=14)
    for v in out:
        if v is None:
            continue
        assert float(v) >= 0.0


@given(seed=st.integers(0, 10_000), n=st.integers(80, 150))
@settings(max_examples=20, deadline=None)
def test_bb_ordering_lower_le_mid_le_upper(seed: int, n: int) -> None:
    bb = bollinger(ohlc_frame(n, seed=seed), period=20, num_std=2.0)
    for i in range(n):
        lo, mid, up = bb["bb_lower_20_2"][i], bb["bb_mid_20_2"][i], bb["bb_upper_20_2"][i]
        if None in (lo, mid, up):
            continue
        assert float(lo) <= float(mid) <= float(up)


@given(seed=st.integers(0, 10_000), n=st.integers(80, 150))
@settings(max_examples=20, deadline=None)
def test_donchian_contains_close(seed: int, n: int) -> None:
    df = ohlc_frame(n, seed=seed)
    d = donchian(df, period=20)
    for i in range(n):
        hi, lo, c = d["donchian_high_20"][i], d["donchian_low_20"][i], df["close"][i]
        if hi is None or lo is None:
            continue
        assert float(lo) <= float(c) <= float(hi)
