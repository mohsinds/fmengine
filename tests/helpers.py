"""Shared OHLC helpers for unit/property tests (not a conftest)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl


def ohlc_frame(n: int = 200, *, seed: int = 0, start: float = 100.0) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0, 0.001, size=n)
    close = start * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[start], close[:-1]])
    high = np.maximum(open_, close) * (1.0 + rng.uniform(0, 0.0005, size=n))
    low = np.minimum(open_, close) * (1.0 - rng.uniform(0, 0.0005, size=n))
    t0 = datetime(2021, 1, 4, 12, 0, tzinfo=UTC)
    ts = [t0 + timedelta(minutes=i) for i in range(n)]
    return pl.DataFrame(
        {
            "ts": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.integers(1, 100, size=n).astype(np.float64),
        }
    )


def constant_ohlc(n: int = 50, price: float = 100.0) -> pl.DataFrame:
    t0 = datetime(2021, 1, 4, 12, 0, tzinfo=UTC)
    ts = [t0 + timedelta(minutes=i) for i in range(n)]
    return pl.DataFrame(
        {
            "ts": ts,
            "open": [price] * n,
            "high": [price] * n,
            "low": [price] * n,
            "close": [price] * n,
            "volume": [1.0] * n,
        }
    )


def assert_no_lookahead(
    compute: Callable[[pl.DataFrame], pl.Series],
    df: pl.DataFrame,
    *,
    index: int,
) -> None:
    full = compute(df)
    trunc = compute(df.head(index + 1))
    fv = full[index]
    tv = trunc[index]
    if fv is None and tv is None:
        return
    if fv is None or tv is None:
        raise AssertionError(f"null mismatch at {index}: full={fv} trunc={tv}")
    assert abs(float(fv) - float(tv)) < 1e-9, f"lookahead at {index}: {fv} vs {tv}"
