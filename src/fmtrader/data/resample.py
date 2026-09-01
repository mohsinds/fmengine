"""Session-aware OHLC resampling (1m → higher timeframes)."""

from __future__ import annotations

import polars as pl

from fmtrader.core.errors import DataError
from fmtrader.data.calendars import SessionCalendar
from fmtrader.data.quality import _in_session_expr

_TIMEFRAME_TO_EVERY: dict[str, str] = {
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
    "1d": "1d",
}


def resample_ohlc(
    frame: pl.DataFrame,
    *,
    target_timeframe: str,
    calendar: SessionCalendar | None = None,
) -> pl.DataFrame:
    """Aggregate 1m bars to ``target_timeframe`` without inventing bars across gaps.

    Only in-session source bars are used when ``calendar`` is provided. Empty buckets
    from gaps are dropped (``group_by_dynamic`` only emits groups with data).
    """
    if target_timeframe not in _TIMEFRAME_TO_EVERY:
        raise DataError(f"Unsupported resample timeframe: {target_timeframe}")
    if frame.is_empty():
        return frame

    work = frame.sort("ts")
    if calendar is not None:
        work = (
            work.with_columns(_in_session_expr(calendar).alias("_in_session"))
            .filter(pl.col("_in_session"))
            .drop("_in_session")
        )

    every = _TIMEFRAME_TO_EVERY[target_timeframe]
    meta = {
        "symbol": work["symbol"][0],
        "instrument_class": work["instrument_class"][0],
    }
    agg = (
        work.group_by_dynamic("ts", every=every, closed="left", label="left")
        .agg(
            pl.col("open").first(),
            pl.col("high").max(),
            pl.col("low").min(),
            pl.col("close").last(),
            pl.col("volume").sum() if "volume" in work.columns else pl.lit(None),
            pl.col("open_interest").last() if "open_interest" in work.columns else pl.lit(None),
            pl.col("bid").last() if "bid" in work.columns else pl.lit(None),
            pl.col("ask").last() if "ask" in work.columns else pl.lit(None),
            pl.col("is_tradable").min() if "is_tradable" in work.columns else pl.lit(True),
        )
        .with_columns(
            pl.lit(meta["symbol"]).alias("symbol"),
            pl.lit(meta["instrument_class"]).alias("instrument_class"),
            pl.lit(target_timeframe).alias("timeframe"),
        )
    )
    return agg.sort("ts")
