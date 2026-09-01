"""As-of join engine and alignment strategies.

Invariant: joins use ``available_time`` with strategy=backward. Never ``event_time``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

import polars as pl

from fmtrader.core.errors import ProviderError
from fmtrader.providers.contracts import AlignmentStrategy, FeatureSpec, PointInTimeRecord

JoinOn = Literal["available_time", "event_time"]


def records_to_frame(
    records: list[PointInTimeRecord], *, value_field: str = "value"
) -> pl.DataFrame:
    """Convert PIT records to a Polars frame for joining."""
    if not records:
        return pl.DataFrame(
            {
                "record_id": pl.Series([], dtype=pl.Utf8),
                "event_time": pl.Series([], dtype=pl.Datetime(time_zone="UTC")),
                "available_time": pl.Series([], dtype=pl.Datetime(time_zone="UTC")),
                "ingestion_time": pl.Series([], dtype=pl.Datetime(time_zone="UTC")),
                "revision_of": pl.Series([], dtype=pl.Utf8),
                "value": pl.Series([], dtype=pl.Float64),
            }
        )
    rows: list[dict[str, object]] = []
    for r in records:
        val = r.payload.get(value_field)
        if val is None and "polarity" in r.payload:
            val = r.payload["polarity"]
        rows.append(
            {
                "record_id": r.record_id,
                "event_time": r.event_time,
                "available_time": r.available_time,
                "ingestion_time": r.ingestion_time,
                "revision_of": r.revision_of,
                "value": float(val) if val is not None else None,
            }
        )
    return pl.DataFrame(rows).sort("available_time")


def apply_safety_lag(records: pl.DataFrame, safety_lag: timedelta) -> pl.DataFrame:
    if safety_lag.total_seconds() <= 0:
        return records
    micros = int(safety_lag.total_seconds() * 1_000_000)
    return records.with_columns(
        (pl.col("available_time") + pl.duration(microseconds=micros)).alias("available_time")
    )


def join_asof_bars(
    bars: pl.DataFrame,
    records: pl.DataFrame,
    *,
    join_on: JoinOn = "available_time",
    safety_lag: timedelta = timedelta(0),
) -> pl.DataFrame:
    """Backward as-of join of records onto bars.

    ``join_on='event_time'`` exists so leakage tests can plant a bad join.
    Production callers must use ``available_time``.
    """
    if "ts" not in bars.columns:
        raise ProviderError("bars frame missing ts")
    empty_cols = [
        pl.lit(None).cast(pl.Float64).alias("_pit_value"),
        pl.lit(None).cast(pl.Datetime(time_zone="UTC")).alias("_pit_available_time"),
        pl.lit(None).cast(pl.Datetime(time_zone="UTC")).alias("_pit_event_time"),
    ]
    if records.is_empty():
        return bars.with_columns(empty_cols)

    rec = apply_safety_lag(records, safety_lag)
    ts_dtype = bars["ts"].dtype
    right = rec.select(
        pl.col(join_on).cast(ts_dtype).alias("_join_key"),
        pl.col("available_time").cast(ts_dtype).alias("_pit_available_time"),
        pl.col("event_time").cast(ts_dtype).alias("_pit_event_time"),
        pl.col("value").alias("_pit_value"),
    ).sort("_join_key")
    return (
        bars.sort("ts")
        .join_asof(
            right,
            left_on="ts",
            right_on="_join_key",
            strategy="backward",
        )
        .drop("_join_key", strict=False)
    )


def assert_join_key_is_available_time(join_on: JoinOn) -> None:
    if join_on != "available_time":
        raise ProviderError(
            f"Look-ahead: join_on={join_on!r} is forbidden; must use available_time"
        )


def align_feature(
    bars: pl.DataFrame,
    records: list[PointInTimeRecord],
    spec: FeatureSpec,
    *,
    safety_lag: timedelta = timedelta(0),
    join_on: JoinOn = "available_time",
) -> pl.Series:
    """Align sparse records to bars using ``spec.alignment`` (trailing windows only)."""
    value_field = spec.alignment.value_field
    frame = records_to_frame(records, value_field=value_field)
    strategy = spec.alignment.strategy

    if strategy in {"last_known", "decay", "impulse", "since_last"}:
        joined = join_asof_bars(bars, frame, join_on=join_on, safety_lag=safety_lag)
        if strategy == "last_known":
            s = joined["_pit_value"]
            return _apply_null_policy(s.rename(spec.name), spec)
        if strategy == "decay":
            assert spec.alignment.half_life is not None
            hl = spec.alignment.half_life.total_seconds()
            if hl <= 0:
                raise ProviderError("half_life must be positive")
            age = (joined["ts"] - joined["_pit_available_time"]).dt.total_seconds().fill_null(0.0)
            decay = (0.5 ** (age / hl)).fill_null(0.0)
            s = (joined["_pit_value"].fill_null(0.0) * decay).rename(spec.name)
            return _apply_null_policy(s, spec)
        if strategy == "impulse":
            s = joined.select(
                pl.when(pl.col("_pit_available_time") == pl.col("ts"))
                .then(pl.col("_pit_value"))
                .otherwise(None)
                .alias(spec.name)
            )[spec.name]
            return _apply_null_policy(s, spec)
        # since_last
        age = (joined["ts"] - joined["_pit_available_time"]).dt.total_seconds()
        div = {"seconds": 1.0, "minutes": 60.0, "hours": 3600.0}[spec.alignment.unit]
        s = (age / div).rename(spec.name)
        return _apply_null_policy(s, spec)

    if strategy in {"window_agg", "count"}:
        return _window_align(bars, frame, spec, safety_lag=safety_lag, join_on=join_on)

    if strategy == "scheduled_proximity":
        return _scheduled_proximity(bars, frame, spec, safety_lag=safety_lag)

    raise ProviderError(f"Unknown alignment strategy: {strategy}")


def _window_align(
    bars: pl.DataFrame,
    records: pl.DataFrame,
    spec: FeatureSpec,
    *,
    safety_lag: timedelta,
    join_on: JoinOn,
) -> pl.Series:
    """Trailing window aggregation — never centered."""
    assert spec.alignment.window is not None
    window_s = spec.alignment.window.total_seconds()
    if window_s <= 0:
        raise ProviderError("window must be positive")
    rec = apply_safety_lag(records, safety_lag)
    if join_on != "available_time":
        rec = rec.with_columns(pl.col("event_time").alias("available_time"))

    ts_list = bars["ts"].to_list()
    if rec.is_empty():
        fill = 0.0 if spec.alignment.strategy == "count" else None
        return _apply_null_policy(pl.Series(spec.name, [fill] * len(ts_list)), spec)

    avail = rec["available_time"].to_list()
    vals = rec["value"].to_list()
    out: list[float | None] = []
    for t in ts_list:
        t_epoch = t.timestamp()
        lo = t_epoch - window_s
        bucket: list[float] = []
        for a, v in zip(avail, vals, strict=True):
            if a is None or v is None:
                continue
            ae = a.timestamp()
            if lo < ae <= t_epoch:
                bucket.append(float(v))
        if spec.alignment.strategy == "count":
            out.append(float(len(bucket)))
        elif not bucket:
            out.append(None)
        else:
            out.append(_agg(bucket, spec.alignment.agg or "mean"))
    return _apply_null_policy(pl.Series(spec.name, out), spec)


def _agg(bucket: list[float], agg: str) -> float:
    if agg == "mean":
        return float(sum(bucket) / len(bucket))
    if agg == "sum":
        return float(sum(bucket))
    if agg == "min":
        return float(min(bucket))
    if agg == "max":
        return float(max(bucket))
    if agg == "last":
        return float(bucket[-1])
    if agg == "std":
        if len(bucket) < 2:
            return 0.0
        m = sum(bucket) / len(bucket)
        return float((sum((x - m) ** 2 for x in bucket) / (len(bucket) - 1)) ** 0.5)
    raise ProviderError(f"Unknown agg: {agg}")


def _scheduled_proximity(
    bars: pl.DataFrame,
    records: pl.DataFrame,
    spec: FeatureSpec,
    *,
    safety_lag: timedelta,
) -> pl.Series:
    """Minutes until the next scheduled event whose schedule was already available."""
    rec = apply_safety_lag(records, safety_lag)
    events: list[tuple[datetime, datetime]] = []
    if not rec.is_empty():
        for a, e in zip(rec["available_time"].to_list(), rec["event_time"].to_list(), strict=True):
            if isinstance(a, datetime) and isinstance(e, datetime):
                events.append((a, e))
    out: list[float | None] = []
    for bar_ts in bars["ts"].to_list():
        if not isinstance(bar_ts, datetime):
            out.append(None)
            continue
        te = bar_ts.timestamp()
        best: float | None = None
        for avail, ev in events:
            ae, ee = avail.timestamp(), ev.timestamp()
            if ae <= te and ee >= te:
                mins = (ee - te) / 60.0
                if best is None or mins < best:
                    best = mins
        out.append(best)
    return _apply_null_policy(pl.Series(spec.name, out), spec)


def _apply_null_policy(s: pl.Series, spec: FeatureSpec) -> pl.Series:
    s = s.rename(spec.name)
    if spec.null_policy == "null":
        return s
    if spec.null_policy == "zero":
        return s.fill_null(0.0)
    if spec.null_policy == "last_known":
        return s.forward_fill()
    if spec.null_policy == "fail":
        if s.null_count() > 0:
            raise ProviderError(f"Feature {spec.name!r} has nulls and null_policy=fail")
        return s
    raise ProviderError(f"Unknown null_policy: {spec.null_policy}")


# Re-export for callers that configure alignment via dict
__all__ = [
    "AlignmentStrategy",
    "FeatureSpec",
    "JoinOn",
    "align_feature",
    "assert_join_key_is_available_time",
    "join_asof_bars",
    "records_to_frame",
]
