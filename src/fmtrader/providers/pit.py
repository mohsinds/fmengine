"""Revision-aware point-in-time record helpers."""

from __future__ import annotations

from datetime import datetime, timedelta

from fmtrader.core.errors import ProviderError
from fmtrader.providers.contracts import PointInTimeRecord, ProviderCapabilities


def validate_record(
    record: PointInTimeRecord,
    caps: ProviderCapabilities,
) -> PointInTimeRecord:
    """Reject backfilled lies about availability for lagged sources."""
    if (caps.enforce_nonzero_lag or caps.typical_publication_lag > timedelta(0)) and (
        record.available_time == record.event_time
    ):
        raise ProviderError(
            "Backfilled record rejected: available_time equals event_time for a "
            f"source with publication lag ({caps.typical_publication_lag})"
        )
    return record


def asof_value(
    records: list[PointInTimeRecord],
    *,
    asof: datetime,
    field: str = "value",
) -> object | None:
    """Latest payload field among records with ``available_time <= asof``.

    Revisions are additive: a later ``available_time`` naturally supersedes.
    """
    visible = [r for r in records if r.available_time <= asof]
    if not visible:
        return None
    best = max(visible, key=lambda r: (r.available_time, r.ingestion_time))
    return best.payload.get(field)


def append_revision(
    records: list[PointInTimeRecord],
    *,
    original_id: str,
    revision: PointInTimeRecord,
) -> list[PointInTimeRecord]:
    """Append a revision; never overwrite the original."""
    if revision.revision_of != original_id:
        raise ProviderError("revision.revision_of must point at the original record_id")
    originals = [r for r in records if r.record_id == original_id]
    if not originals:
        raise ProviderError(f"Original record {original_id!r} not found")
    # Keep original intact
    return [*records, revision]
