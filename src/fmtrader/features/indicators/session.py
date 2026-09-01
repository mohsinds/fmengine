"""Session / calendar features — deterministic from bar-open timestamps."""

from __future__ import annotations

import polars as pl
from pydantic import BaseModel, Field

from fmtrader.features.registry import register_indicator


class EmptyParams(BaseModel):
    pass


class SessionOpenParams(BaseModel):
    """FX week open: Sunday 22:00 UTC by default (XAUUSD)."""

    week_open_weekday: int = Field(default=6, ge=0, le=6)  # Sunday
    week_open_hour: int = Field(default=22, ge=0, le=23)
    week_open_minute: int = Field(default=0, ge=0, le=59)


@register_indicator(
    name="minute_of_day",
    category="session",
    requires=("ts",),
    min_lookback=1,
    params_schema=EmptyParams,
)
def minute_of_day(df: pl.DataFrame) -> pl.Series:
    """Minutes since midnight UTC."""
    return (df["ts"].dt.hour().cast(pl.Int32) * 60 + df["ts"].dt.minute().cast(pl.Int32)).rename(
        "minute_of_day"
    )


@register_indicator(
    name="day_of_week",
    category="session",
    requires=("ts",),
    min_lookback=1,
    params_schema=EmptyParams,
)
def day_of_week(df: pl.DataFrame) -> pl.Series:
    """Python weekday Mon=0 … Sun=6."""
    return (df["ts"].dt.weekday() - 1).rename("day_of_week")


@register_indicator(
    name="session_bucket",
    category="session",
    requires=("ts",),
    min_lookback=1,
    params_schema=EmptyParams,
)
def session_bucket(df: pl.DataFrame) -> pl.Series:
    """Coarse session bucket: asia=0, london=1, ny=2, off=3 (UTC hours)."""
    h = df["ts"].dt.hour()
    # Asia 00-07, London 07-12, NY 12-21, else off/rollover
    bucket = (
        pl.when((h >= 0) & (h < 7))
        .then(0)
        .when((h >= 7) & (h < 12))
        .then(1)
        .when((h >= 12) & (h < 21))
        .then(2)
        .otherwise(3)
    )
    return df.select(bucket.alias("session_bucket")).to_series()


@register_indicator(
    name="time_since_session_open",
    category="session",
    requires=("ts",),
    min_lookback=1,
    params_schema=SessionOpenParams,
)
def time_since_session_open(
    df: pl.DataFrame,
    week_open_weekday: int = 6,
    week_open_hour: int = 22,
    week_open_minute: int = 0,
) -> pl.Series:
    """Minutes since the most recent weekly session open (Sun 22:00 UTC)."""
    # Polars ISO weekday Mon=1..Sun=7 → Python Mon=0..Sun=6
    py_wd = (df["ts"].dt.weekday() - 1).cast(pl.Int32)
    minutes = df["ts"].dt.hour().cast(pl.Int32) * 60 + df["ts"].dt.minute().cast(pl.Int32)
    open_m = week_open_hour * 60 + week_open_minute
    # Minutes since Sunday 00:00 within week, then subtract open offset
    since_sun_midnight = py_wd * 1440 + minutes
    open_since_sun = week_open_weekday * 1440 + open_m
    delta = since_sun_midnight - open_since_sun
    # Wrap negative (before open Sunday) into previous week length
    week_len = 7 * 1440
    wrapped = pl.when(delta < 0).then(delta + week_len).otherwise(delta)
    return df.select(wrapped.cast(pl.Int32).alias("time_since_session_open")).to_series()
