"""Leakage detectors for provider / as-of join bugs."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fmtrader.core.errors import ProviderError, ValidationError
from fmtrader.providers.alignment import JoinOn, assert_join_key_is_available_time
from fmtrader.providers.contracts import PointInTimeRecord, ProviderCapabilities
from fmtrader.providers.pit import validate_record


def catch_event_time_join(join_on: JoinOn) -> None:
    """Planted event_time join must be rejected."""
    try:
        assert_join_key_is_available_time(join_on)
    except ProviderError as exc:
        raise ValidationError(str(exc)) from exc
    raise ValidationError("Expected event_time join to be caught")


def catch_restated_value_used_before_available(
    *,
    value_used: Any,
    restated_value: Any,
    asof: datetime,
    restatement_available: datetime,
) -> None:
    """Using the restated value before its available_time is leakage."""
    if asof < restatement_available and value_used == restated_value:
        raise ValidationError(
            f"Restated value leaked into history at {asof}: used {value_used!r} "
            f"before available_time {restatement_available}"
        )


def catch_backfilled_equal_times(
    record: PointInTimeRecord,
    *,
    lag: timedelta,
) -> None:
    caps = ProviderCapabilities(typical_publication_lag=lag, enforce_nonzero_lag=True)
    try:
        validate_record(record, caps)
    except ProviderError as exc:
        raise ValidationError(str(exc)) from exc
    raise ValidationError("Expected backfilled equal-time record to be rejected")


def catch_future_scored_sentiment(
    *,
    scored_at: datetime,
    bar_ts: datetime,
    used_at_bar: bool,
) -> None:
    """Sentiment scored after the bar must not be used at that bar."""
    if used_at_bar and scored_at > bar_ts:
        raise ValidationError(
            f"Future-scored sentiment used at bar {bar_ts} (scored_at={scored_at})"
        )


def catch_negative_lag(event_time: datetime, available_time: datetime) -> None:
    if available_time < event_time:
        raise ValidationError(
            f"Negative publication lag: available_time {available_time} < event_time {event_time}"
        )
