"""Data quality gate — hard-fail on structural problems, report the rest."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import polars as pl
from rich.console import Console
from rich.table import Table

from fmtrader.core.errors import QualityError
from fmtrader.data.calendars import SessionCalendar

console = Console()


@dataclass
class QualityReport:
    """Structured quality report persisted into the snapshot manifest."""

    rows: int
    start: str | None
    end: str | None
    duplicate_timestamps: int = 0
    non_monotonic: bool = False
    ohlc_violations: int = 0
    non_positive_prices: int = 0
    flat_bar_runs: int = 0
    flat_bar_rows: int = 0
    mad_outliers: int = 0
    gaps: dict[str, int] = field(default_factory=dict)
    coverage_by_month: list[dict[str, Any]] = field(default_factory=list)
    hard_fail_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def ok(self) -> bool:
        return not self.hard_fail_reasons


def _in_session_expr(calendar: SessionCalendar) -> pl.Expr:
    """Vectorized in-session predicate (Polars ISO weekday: Mon=1 … Sun=7)."""
    # Convert to Python weekday Mon=0 … Sun=6.
    # Cast to Int32: hour*60 overflows i8 (e.g. 21*60 → -20).
    py_wd = pl.col("ts").dt.weekday().cast(pl.Int32) - 1
    minutes = pl.col("ts").dt.hour().cast(pl.Int32) * 60 + pl.col("ts").dt.minute().cast(pl.Int32)
    week_open_m = calendar.week_open_hour * 60 + calendar.week_open_minute
    week_close_m = calendar.week_close_hour * 60 + calendar.week_close_minute

    holiday_dates = {d.date().isoformat() for d in calendar.holidays}
    is_holiday = pl.col("ts").dt.strftime("%Y-%m-%d").is_in(list(holiday_dates))

    saturday = py_wd == 5
    before_sun_open = (py_wd == calendar.week_open_weekday) & (minutes < week_open_m)
    after_fri_close = (py_wd == calendar.week_close_weekday) & (minutes >= week_close_m)

    return ~(is_holiday | saturday | before_sun_open | after_fri_close)


def _annotate_tradable(frame: pl.DataFrame, *, min_run: int = 3) -> pl.DataFrame:
    """Add ``is_tradable``: false for flat runs and out-of-session bars."""
    is_flat = (
        (pl.col("high") == pl.col("low"))
        & (pl.col("open") == pl.col("close"))
        & (pl.col("open") == pl.col("high"))
    )
    changed = is_flat.cast(pl.Int8).diff().fill_null(1).abs() > 0
    run_id = changed.cum_sum()
    with_runs = frame.with_columns(is_flat.alias("_is_flat"), run_id.alias("_run_id"))
    run_sizes = with_runs.group_by("_run_id").agg(
        pl.len().alias("_run_len"),
        pl.col("_is_flat").first().alias("_run_flat"),
    )
    joined = with_runs.join(run_sizes, on="_run_id")
    is_tradable = ~(
        (~pl.col("_in_session")) | (pl.col("_run_flat") & (pl.col("_run_len") >= min_run))
    )
    return joined.with_columns(is_tradable.alias("is_tradable")).drop(
        "_is_flat", "_run_id", "_run_len", "_run_flat"
    )


def _mad_outlier_count(closes: np.ndarray, *, z: float = 8.0) -> int:
    if closes.size < 3:
        return 0
    rets = np.diff(np.log(np.asarray(closes, dtype=np.float64)))
    med = float(np.median(rets))
    mad = float(np.median(np.abs(rets - med)))
    if mad == 0.0 or np.isnan(mad):
        # Degenerate series: any non-zero return is an outlier
        return int(np.sum(np.abs(rets - med) > 1e-12))
    score = np.abs(rets - med) / (1.4826 * mad)
    return int(np.sum(score > z))


def _expected_minutes(lo: datetime, hi: datetime, calendar: SessionCalendar) -> int:
    """Count expected in-session minutes in [lo, hi)."""
    if hi <= lo:
        return 0
    rng = pl.datetime_range(
        lo, hi - timedelta(minutes=1), interval="1m", eager=True, time_zone="UTC"
    )
    if rng.is_empty():
        return 0
    tmp = pl.DataFrame({"ts": rng}).with_columns(_in_session_expr(calendar).alias("_in"))
    return int(tmp.filter(pl.col("_in")).height)


def _coverage_by_month(frame: pl.DataFrame, calendar: SessionCalendar) -> list[dict[str, Any]]:
    """Monthly coverage of **in-session** bars vs calendar-expected minutes.

    Vendor files often include out-of-session rows (Sunday pre-open, Friday
    post-close). Those are kept in the catalog but excluded from coverage so
    the ratio stays near 100% when the session is complete.
    """
    if frame.is_empty():
        return []
    start = frame["ts"].min()
    end = frame["ts"].max()
    assert isinstance(start, datetime) and isinstance(end, datetime)

    if "_in_session" not in frame.columns:
        work = frame.with_columns(_in_session_expr(calendar).alias("_in_session"))
    else:
        work = frame

    obs = (
        work.with_columns(pl.col("ts").dt.strftime("%Y-%m").alias("month"))
        .group_by("month")
        .agg(
            pl.len().alias("observed_total"),
            pl.col("_in_session").sum().alias("observed"),
        )
        .sort("month")
    )
    rows: list[dict[str, Any]] = []
    for rec in obs.to_dicts():
        month = str(rec["month"])
        year_s, mon_s = month.split("-")
        year, mon = int(year_s), int(mon_s)
        month_start = datetime(year, mon, 1, tzinfo=UTC)
        month_end = (
            datetime(year + 1, 1, 1, tzinfo=UTC)
            if mon == 12
            else datetime(year, mon + 1, 1, tzinfo=UTC)
        )
        lo = max(month_start, start.replace(second=0, microsecond=0))
        hi = min(month_end, end + timedelta(minutes=1))
        expected = _expected_minutes(lo, hi, calendar)
        observed = int(rec["observed"])
        pct = (100.0 * observed / expected) if expected else 0.0
        rows.append(
            {
                "month": month,
                "observed": observed,
                "observed_total": int(rec["observed_total"]),
                "expected": expected,
                "coverage_pct": round(pct, 2),
            }
        )
    return rows


def run_quality_gate(
    frame: pl.DataFrame,
    calendar: SessionCalendar,
    *,
    mad_z: float = 8.0,
    flat_run_min: int = 3,
    hard_fail: bool = True,
) -> tuple[pl.DataFrame, QualityReport]:
    """Validate and annotate ``frame``; optionally raise on structural failures."""
    report = QualityReport(rows=frame.height, start=None, end=None)
    if frame.is_empty():
        report.hard_fail_reasons.append("empty frame")
        if hard_fail:
            raise QualityError("Quality gate failed: empty frame")
        return frame, report

    work = frame.with_columns(_in_session_expr(calendar).alias("_in_session"))

    dup = work.height - work.select("ts").unique().height
    report.duplicate_timestamps = dup
    report.non_monotonic = not bool(work.select("ts").to_series().is_sorted())
    if dup:
        report.hard_fail_reasons.append(f"duplicate timestamps: {dup}")
    if report.non_monotonic:
        report.hard_fail_reasons.append("timestamps not strictly monotonic")

    ohlc_bad = work.filter(
        (pl.col("low") > pl.min_horizontal("open", "close"))
        | (pl.col("high") < pl.max_horizontal("open", "close"))
    ).height
    non_pos = work.filter(
        (pl.col("open") <= 0)
        | (pl.col("high") <= 0)
        | (pl.col("low") <= 0)
        | (pl.col("close") <= 0)
    ).height
    report.ohlc_violations = ohlc_bad
    report.non_positive_prices = non_pos
    if ohlc_bad:
        report.hard_fail_reasons.append(f"OHLC invariant violations: {ohlc_bad}")
    if non_pos:
        report.hard_fail_reasons.append(f"non-positive prices: {non_pos}")

    work = work.sort("ts")
    report.start = work["ts"][0].isoformat()
    report.end = work["ts"][-1].isoformat()

    ts_list = work["ts"].to_list()
    gaps: dict[str, int] = {"weekend": 0, "holiday": 0, "rollover": 0, "anomalous": 0}
    gap_idx = (
        work.with_row_index("i")
        .with_columns(pl.col("ts").diff().alias("d"))
        .filter(pl.col("d") > pl.duration(minutes=1))
        .select("i")
        .to_series()
        .to_list()
    )
    for i in gap_idx:
        kind = calendar.classify_gap(ts_list[i - 1], ts_list[i])
        if kind in gaps:
            gaps[kind] += 1
    report.gaps = gaps

    annotated = _annotate_tradable(work, min_run=flat_run_min)
    report.flat_bar_rows = int(
        annotated.filter((~pl.col("is_tradable")) & pl.col("_in_session")).height
    )
    flat_mask = (
        (pl.col("high") == pl.col("low"))
        & (pl.col("open") == pl.col("close"))
        & (pl.col("open") == pl.col("high"))
    )
    tmp = annotated.with_columns(
        flat_mask.alias("_f"),
        flat_mask.cast(pl.Int8).diff().fill_null(1).abs().cum_sum().alias("rid"),
    )
    runs = (
        tmp.group_by("rid")
        .agg(pl.col("_f").first().alias("flat"), pl.len().alias("n"))
        .filter(pl.col("flat") & (pl.col("n") >= flat_run_min))
    )
    report.flat_bar_runs = runs.height
    report.mad_outliers = _mad_outlier_count(annotated["close"].to_numpy(), z=mad_z)
    report.coverage_by_month = _coverage_by_month(annotated, calendar)

    if hard_fail and report.hard_fail_reasons:
        raise QualityError("Quality gate hard-fail: " + "; ".join(report.hard_fail_reasons))

    return annotated.drop("_in_session"), report


def print_coverage_table(report: QualityReport) -> None:
    """Pretty-print the monthly coverage table (in-session observed vs expected)."""
    table = Table(title="Monthly coverage (in-session)")
    table.add_column("Month")
    table.add_column("In-session", justify="right")
    table.add_column("Expected", justify="right")
    table.add_column("Coverage %", justify="right")
    for row in report.coverage_by_month:
        table.add_row(
            row["month"],
            str(row["observed"]),
            str(row["expected"]),
            f"{row['coverage_pct']:.2f}",
        )
    console.print(table)
    console.print(
        f"Gaps: {report.gaps} | flat runs: {report.flat_bar_runs} | "
        f"MAD outliers: {report.mad_outliers} | rows: {report.rows}"
    )
