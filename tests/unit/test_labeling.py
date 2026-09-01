"""Labeling unit tests."""

from __future__ import annotations

import numpy as np
import polars as pl

from fmtrader.features.labeling import TripleBarrierConfig, meta_labels, triple_barrier_labels
from tests.helpers import ohlc_frame


def test_triple_barrier_first_touch_wins() -> None:
    # Construct a path that hits PT before SL
    n = 40
    close = np.full(n, 100.0)
    high = np.full(n, 100.0)
    low = np.full(n, 100.0)
    # ATR will be ~0 on flat then we spike
    close[20:] = 100.0
    high[25] = 110.0  # PT touch if ATR small — use large move
    df = ohlc_frame(n).with_columns(
        pl.Series("open", close),
        pl.Series("high", high),
        pl.Series("low", low),
        pl.Series("close", close),
    )
    # Force ATR via prior volatility
    rng_close = np.linspace(100, 105, n)
    rng_close[25] = 105
    high2 = rng_close.copy()
    high2[25] = 120.0
    low2 = rng_close.copy()
    df = df.with_columns(
        pl.Series("open", rng_close),
        pl.Series("close", rng_close),
        pl.Series("high", high2),
        pl.Series("low", low2),
    )
    tb = triple_barrier_labels(
        df, TripleBarrierConfig(atr_period=5, pt_mult=1.0, sl_mult=1.0, max_horizon=10)
    )
    # Some label at t before the spike should be +1
    labels = [tb["tb_label"][i] for i in range(10, 24) if tb["tb_label"][i] is not None]
    assert 1.0 in labels


def test_time_barrier_applies_when_no_touch() -> None:
    df = ohlc_frame(80, seed=1)
    # Tiny barriers unlikely — use huge mult so only time hits
    tb = triple_barrier_labels(
        df, TripleBarrierConfig(atr_period=14, pt_mult=1000.0, sl_mult=1000.0, max_horizon=5)
    )
    # After ATR warmup, labels should be 0 (time)
    vals = [tb["tb_label"][i] for i in range(30, 50) if tb["tb_label"][i] is not None]
    assert vals and all(v == 0.0 for v in vals)


def test_barriers_scale_with_atr() -> None:
    df = ohlc_frame(100, seed=2)
    tight = triple_barrier_labels(
        df, TripleBarrierConfig(atr_period=14, pt_mult=0.5, sl_mult=0.5, max_horizon=30)
    )
    wide = triple_barrier_labels(
        df, TripleBarrierConfig(atr_period=14, pt_mult=5.0, sl_mult=5.0, max_horizon=30)
    )
    # Wider barriers → longer average touch horizon
    t_touch = np.nanmean(tight["tb_touch_bars"].to_numpy().astype(float))
    w_touch = np.nanmean(wide["tb_touch_bars"].to_numpy().astype(float))
    assert w_touch >= t_touch


def test_no_label_uses_future_beyond_its_own_window() -> None:
    df = ohlc_frame(60, seed=3)
    cfg = TripleBarrierConfig(atr_period=5, pt_mult=2.0, sl_mult=2.0, max_horizon=10)
    full = triple_barrier_labels(df, cfg)
    trunc = triple_barrier_labels(df.head(40), cfg)
    # Label at index 25 only looks ahead to 35 — must match truncated series
    assert full["tb_label"][25] == trunc["tb_label"][25]
    assert full["tb_touch_bars"][25] == trunc["tb_touch_bars"][25]


def test_sample_weights_sum_sensibly_under_overlap() -> None:
    df = ohlc_frame(80, seed=4)
    tb = triple_barrier_labels(
        df, TripleBarrierConfig(atr_period=10, pt_mult=1.0, sl_mult=1.0, max_horizon=15)
    )
    w = tb["sample_weight"].drop_nulls()
    assert w.len() > 0
    assert float(w.min()) > 0.0
    assert float(w.max()) <= 1.0 + 1e-9


def test_meta_labels_match_side() -> None:
    df = ohlc_frame(50, seed=5)
    tb = triple_barrier_labels(
        df, TripleBarrierConfig(atr_period=5, pt_mult=1.5, sl_mult=1.5, max_horizon=10)
    )
    side = pl.Series("side", [1.0] * df.height)
    meta = meta_labels(side, tb)
    for i in range(df.height):
        lab = tb["tb_label"][i]
        if lab is None or (isinstance(lab, float) and np.isnan(lab)):
            continue
        expected = 1.0 if lab == 1.0 else 0.0
        assert meta[i] == expected
