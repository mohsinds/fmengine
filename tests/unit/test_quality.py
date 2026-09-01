"""Quality gate unit tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from fmtrader.core.errors import QualityError
from fmtrader.data.calendars import XAUUSD_FX
from fmtrader.data.quality import run_quality_gate


def _frame(rows: list[tuple[datetime, float, float, float, float]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ts": [r[0] for r in rows],
            "symbol": ["XAUUSD"] * len(rows),
            "instrument_class": ["spot_cfd"] * len(rows),
            "timeframe": ["1m"] * len(rows),
            "open": [r[1] for r in rows],
            "high": [r[2] for r in rows],
            "low": [r[3] for r in rows],
            "close": [r[4] for r in rows],
            "volume": [None] * len(rows),
            "open_interest": [None] * len(rows),
            "bid": [r[4] for r in rows],
            "ask": [None] * len(rows),
        }
    )


def test_detects_duplicate_timestamps() -> None:
    t0 = datetime(2021, 1, 4, 12, 0, tzinfo=UTC)  # Monday
    frame = _frame(
        [
            (t0, 1, 1, 1, 1),
            (t0, 1, 1, 1, 1),
        ]
    )
    with pytest.raises(QualityError, match="duplicate"):
        run_quality_gate(frame, XAUUSD_FX)


def test_detects_non_monotonic_timestamps() -> None:
    t0 = datetime(2021, 1, 4, 12, 0, tzinfo=UTC)
    t1 = t0 + timedelta(minutes=1)
    frame = _frame([(t1, 1, 1, 1, 1), (t0, 1, 1, 1, 1)])
    with pytest.raises(QualityError, match="monotonic"):
        run_quality_gate(frame, XAUUSD_FX)


def test_detects_ohlc_invariant_violation() -> None:
    t0 = datetime(2021, 1, 4, 12, 0, tzinfo=UTC)
    frame = _frame([(t0, 10, 9, 8, 9.5)])  # high < open
    with pytest.raises(QualityError, match="OHLC"):
        run_quality_gate(frame, XAUUSD_FX)


def test_classifies_weekend_gap_correctly() -> None:
    # Friday 20:59 → Sunday 22:00
    fri = datetime(2021, 1, 8, 20, 59, tzinfo=UTC)
    sun = datetime(2021, 1, 10, 22, 0, tzinfo=UTC)
    frame = _frame([(fri, 1, 1, 1, 1), (sun, 1, 1, 1, 1)])
    _, report = run_quality_gate(frame, XAUUSD_FX)
    assert report.gaps.get("weekend", 0) >= 1


def test_classifies_holiday_gap_correctly() -> None:
    # Christmas 2025 (Thursday) is in the holiday set — gap entirely on that day
    from fmtrader.data.calendars import XAUUSD_FX as cal

    prev = datetime(2025, 12, 25, 0, 0, tzinfo=UTC)
    curr = datetime(2025, 12, 25, 12, 0, tzinfo=UTC)
    assert cal.classify_gap(prev, curr) == "holiday"


def test_flags_anomalous_gap() -> None:
    t0 = datetime(2021, 1, 4, 12, 0, tzinfo=UTC)
    t1 = t0 + timedelta(minutes=30)  # 29 missing in-session minutes
    frame = _frame([(t0, 1, 1, 1, 1), (t1, 1, 1, 1, 1)])
    _, report = run_quality_gate(frame, XAUUSD_FX)
    assert report.gaps.get("anomalous", 0) >= 1


def test_detects_flat_bar_runs() -> None:
    t0 = datetime(2021, 1, 4, 12, 0, tzinfo=UTC)
    rows = [(t0 + timedelta(minutes=i), 5.0, 5.0, 5.0, 5.0) for i in range(5)]
    frame = _frame(rows)
    out, report = run_quality_gate(frame, XAUUSD_FX)
    assert report.flat_bar_runs >= 1
    assert out.filter(~pl.col("is_tradable")).height >= 5


def test_mad_outlier_detection_flags_spike() -> None:
    t0 = datetime(2021, 1, 4, 12, 0, tzinfo=UTC)
    rows = [(t0 + timedelta(minutes=i), 100.0, 100.0, 100.0, 100.0) for i in range(50)]
    # Spike
    rows.append((t0 + timedelta(minutes=50), 100.0, 200.0, 100.0, 200.0))
    rows.append((t0 + timedelta(minutes=51), 200.0, 200.0, 200.0, 200.0))
    frame = _frame(rows)
    _, report = run_quality_gate(frame, XAUUSD_FX)
    assert report.mad_outliers >= 1


def test_coverage_table_sums_to_total() -> None:
    t0 = datetime(2021, 1, 4, 12, 0, tzinfo=UTC)
    rows = [(t0 + timedelta(minutes=i), 1.0, 1.1, 0.9, 1.0) for i in range(10)]
    frame = _frame(rows)
    _, report = run_quality_gate(frame, XAUUSD_FX)
    assert sum(r["observed_total"] for r in report.coverage_by_month) == report.rows
    assert all(r["coverage_pct"] <= 100.01 for r in report.coverage_by_month)


def test_friday_evening_bars_not_tradable() -> None:
    fri = datetime(2021, 1, 8, 21, 0, tzinfo=UTC)
    frame = _frame([(fri, 1.0, 1.0, 1.0, 1.0)])
    out, _ = run_quality_gate(frame, XAUUSD_FX)
    assert out["is_tradable"][0] is False
