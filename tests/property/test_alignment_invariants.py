"""Property: past feature values never change when future records are appended."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
from hypothesis import given, settings
from hypothesis import strategies as st

from fmtrader.providers.alignment import align_feature
from fmtrader.providers.contracts import AlignmentStrategy, FeatureSpec, PointInTimeRecord


def _bars(n: int, start: datetime) -> pl.DataFrame:
    return pl.DataFrame({"ts": [start + timedelta(minutes=i) for i in range(n)]})


@given(
    n_past=st.integers(5, 20),
    n_future=st.integers(1, 10),
    seed=st.integers(0, 10_000),
)
@settings(max_examples=30, deadline=None)
def test_no_feature_value_at_t_changes_when_future_records_added(
    n_past: int, n_future: int, seed: int
) -> None:
    t0 = datetime(2021, 1, 4, 12, 0, tzinfo=UTC)
    bars = _bars(n_past + n_future, t0)
    cutoff = t0 + timedelta(minutes=n_past - 1)

    past_records = [
        PointInTimeRecord(
            record_id=f"p{i}",
            event_time=t0 + timedelta(minutes=i),
            available_time=t0 + timedelta(minutes=i + 1),
            ingestion_time=t0 + timedelta(minutes=i + 1),
            payload={"value": float((seed + i) % 17)},
        )
        for i in range(max(1, n_past // 2))
    ]
    spec = FeatureSpec(
        name="v",
        alignment=AlignmentStrategy(strategy="last_known"),
        null_policy="null",
    )
    before = align_feature(bars.head(n_past), past_records, spec)

    future_records = [
        PointInTimeRecord(
            record_id=f"f{i}",
            event_time=cutoff + timedelta(minutes=i + 1),
            available_time=cutoff + timedelta(minutes=i + 2),
            ingestion_time=cutoff + timedelta(minutes=i + 2),
            payload={"value": float(100 + i)},
        )
        for i in range(n_future)
    ]
    after = align_feature(bars.head(n_past), past_records + future_records, spec)
    assert before.to_list() == after.to_list()
