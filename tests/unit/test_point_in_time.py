"""Point-in-time record contract tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fmtrader.core.errors import ProviderError
from fmtrader.providers.contracts import PointInTimeRecord, ProviderCapabilities
from fmtrader.providers.pit import append_revision, asof_value, validate_record


def _rec(
    rid: str,
    event: datetime,
    available: datetime,
    *,
    value: float,
    revision_of: str | None = None,
) -> PointInTimeRecord:
    return PointInTimeRecord(
        record_id=rid,
        event_time=event,
        available_time=available,
        ingestion_time=available + timedelta(seconds=1),
        revision_of=revision_of,
        payload={"value": value},
    )


def test_record_requires_event_and_available_time() -> None:
    t = datetime(2024, 1, 1, tzinfo=UTC)
    r = _rec("a", t, t + timedelta(days=1), value=1.0)
    assert r.event_time == t
    assert r.available_time > r.event_time


def test_available_time_never_precedes_event_time() -> None:
    t = datetime(2024, 1, 1, tzinfo=UTC)
    with pytest.raises(ProviderError, match="must not precede"):
        _rec("a", t, t - timedelta(hours=1), value=1.0)


def test_revision_does_not_overwrite_original() -> None:
    t0 = datetime(2024, 3, 31, tzinfo=UTC)
    original = _rec("orig", t0, datetime(2024, 4, 28, tzinfo=UTC), value=1.20)
    restatement = _rec(
        "rev1",
        t0,
        datetime(2024, 11, 12, tzinfo=UTC),
        value=1.05,
        revision_of="orig",
    )
    records = append_revision([original], original_id="orig", revision=restatement)
    assert len(records) == 2
    assert records[0].payload["value"] == 1.20
    assert records[1].payload["value"] == 1.05


def test_asof_returns_pre_revision_value_before_restatement_date() -> None:
    t0 = datetime(2024, 3, 31, tzinfo=UTC)
    original = _rec("orig", t0, datetime(2024, 4, 28, tzinfo=UTC), value=1.20)
    restatement = _rec(
        "rev1",
        t0,
        datetime(2024, 11, 12, tzinfo=UTC),
        value=1.05,
        revision_of="orig",
    )
    records = [original, restatement]
    assert asof_value(records, asof=datetime(2024, 6, 1, tzinfo=UTC)) == 1.20
    assert asof_value(records, asof=datetime(2024, 11, 13, tzinfo=UTC)) == 1.05


def test_backfilled_record_with_equal_times_rejected_for_lagged_source() -> None:
    t = datetime(2024, 1, 1, tzinfo=UTC)
    rec = _rec("b", t, t, value=1.0)
    caps = ProviderCapabilities(
        typical_publication_lag=timedelta(days=1),
        enforce_nonzero_lag=True,
    )
    with pytest.raises(ProviderError, match="Backfilled record rejected"):
        validate_record(rec, caps)
