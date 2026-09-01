"""As-of join and alignment strategy tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl

from fmtrader.providers.alignment import align_feature, join_asof_bars, records_to_frame
from fmtrader.providers.contracts import AlignmentStrategy, FeatureSpec, PointInTimeRecord


def _bars(n: int = 10, start: datetime | None = None) -> pl.DataFrame:
    t0 = start or datetime(2021, 1, 4, 12, 0, tzinfo=UTC)
    return pl.DataFrame({"ts": [t0 + timedelta(minutes=i) for i in range(n)]})


def _rec(
    rid: str,
    event: datetime,
    available: datetime,
    value: float,
) -> PointInTimeRecord:
    return PointInTimeRecord(
        record_id=rid,
        event_time=event,
        available_time=available,
        ingestion_time=available,
        payload={"value": value},
    )


def test_join_uses_available_time_not_event_time() -> None:
    """THE critical test: event happens at t0, published at t0+5 — invisible until then."""
    t0 = datetime(2021, 1, 4, 12, 0, tzinfo=UTC)
    bars = _bars(10, t0)
    records = [_rec("e1", t0, t0 + timedelta(minutes=5), value=42.0)]
    spec = FeatureSpec(name="v", alignment=AlignmentStrategy(strategy="last_known"))
    s = align_feature(bars, records, spec, join_on="available_time")
    # Bars 0..4: not yet available
    assert all(v is None for v in s.head(5).to_list())
    # Bar 5 onward: visible
    assert s[5] == 42.0


def test_record_published_after_bar_is_not_visible() -> None:
    t0 = datetime(2021, 1, 4, 12, 0, tzinfo=UTC)
    bars = _bars(3, t0)
    # Published after last bar
    records = [_rec("e1", t0, t0 + timedelta(minutes=10), value=1.0)]
    spec = FeatureSpec(name="v", alignment=AlignmentStrategy(strategy="last_known"))
    s = align_feature(bars, records, spec)
    assert all(v is None for v in s.to_list())


def test_publication_lag_parameter_respected() -> None:
    t0 = datetime(2021, 1, 4, 12, 0, tzinfo=UTC)
    bars = _bars(10, t0)
    # available at t0+1, but safety_lag +4m → visible at t0+5
    records = [_rec("e1", t0, t0 + timedelta(minutes=1), value=7.0)]
    spec = FeatureSpec(name="v", alignment=AlignmentStrategy(strategy="last_known"))
    s = align_feature(bars, records, spec, safety_lag=timedelta(minutes=4))
    assert all(v is None for v in s.head(5).to_list())
    assert s[5] == 7.0


def test_decay_halflife_produces_expected_weights() -> None:
    t0 = datetime(2021, 1, 4, 12, 0, tzinfo=UTC)
    bars = _bars(61, t0)
    records = [_rec("e1", t0, t0, value=1.0)]
    spec = FeatureSpec(
        name="d",
        alignment=AlignmentStrategy(strategy="decay", half_life=timedelta(minutes=60)),
        null_policy="zero",
    )
    s = align_feature(bars, records, spec)
    # At t0: weight 1. At +60m: weight 0.5
    assert abs(float(s[0]) - 1.0) < 1e-6
    assert abs(float(s[60]) - 0.5) < 1e-6


def test_sparse_records_dense_bars_no_forward_leak() -> None:
    t0 = datetime(2021, 1, 4, 12, 0, tzinfo=UTC)
    bars = _bars(20, t0)
    records = [
        _rec("a", t0 + timedelta(minutes=5), t0 + timedelta(minutes=5), value=1.0),
        _rec("b", t0 + timedelta(minutes=15), t0 + timedelta(minutes=15), value=2.0),
    ]
    # Bad join on event_time would show value earlier if event < available —
    # here equal times; use lag case:
    records = [
        _rec("a", t0, t0 + timedelta(minutes=5), value=1.0),
    ]
    frame = records_to_frame(records)
    good = join_asof_bars(bars, frame, join_on="available_time")
    bad = join_asof_bars(bars, frame, join_on="event_time")
    # event_time join leaks: bar 0 sees the value
    assert bad["_pit_value"][0] == 1.0
    assert good["_pit_value"][0] is None


def test_count_excludes_records_published_after_bar() -> None:
    t0 = datetime(2021, 1, 4, 12, 0, tzinfo=UTC)
    bars = _bars(20, t0)
    records = [
        _rec("a", t0 + timedelta(minutes=2), t0 + timedelta(minutes=2), value=1.0),
        _rec("b", t0 + timedelta(minutes=10), t0 + timedelta(minutes=10), value=1.0),
    ]
    spec = FeatureSpec(
        name="c",
        alignment=AlignmentStrategy(strategy="count", window=timedelta(minutes=15)),
        null_policy="zero",
    )
    s = align_feature(bars, records, spec)
    assert float(s[1]) == 0.0  # before first publish
    assert float(s[2]) == 1.0
    assert float(s[10]) == 2.0


def test_window_agg_is_trailing_not_centered() -> None:
    t0 = datetime(2021, 1, 4, 12, 0, tzinfo=UTC)
    bars = _bars(10, t0)
    # Record only in the future relative to bar 0
    records = [_rec("f", t0 + timedelta(minutes=5), t0 + timedelta(minutes=5), value=9.0)]
    spec = FeatureSpec(
        name="m",
        alignment=AlignmentStrategy(strategy="window_agg", window=timedelta(minutes=3), agg="mean"),
        null_policy="null",
    )
    s = align_feature(bars, records, spec)
    # Bar 0 window is (-3, 0] — must not include future record at +5
    assert s[0] is None
    assert s[5] == 9.0
