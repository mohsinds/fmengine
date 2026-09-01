"""Provider leakage adversarial suite."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fmtrader.core.errors import ValidationError
from fmtrader.providers.contracts import PointInTimeRecord
from fmtrader.providers.leakage import (
    catch_backfilled_equal_times,
    catch_event_time_join,
    catch_future_scored_sentiment,
    catch_negative_lag,
    catch_restated_value_used_before_available,
)


def test_planted_event_time_join_is_caught() -> None:
    with pytest.raises(ValidationError, match="available_time"):
        catch_event_time_join("event_time")


def test_restated_value_used_in_history_is_caught() -> None:
    restatement_available = datetime(2024, 11, 12, tzinfo=UTC)
    asof = datetime(2024, 6, 1, tzinfo=UTC)
    # Planted bug: strategy used restated 1.05 in June
    with pytest.raises(ValidationError, match="Restated value leaked"):
        catch_restated_value_used_before_available(
            value_used=1.05,
            restated_value=1.05,
            asof=asof,
            restatement_available=restatement_available,
        )


def test_backfilled_record_without_available_time_is_rejected() -> None:
    t = datetime(2024, 1, 1, tzinfo=UTC)
    rec = PointInTimeRecord(
        record_id="bf",
        event_time=t,
        available_time=t,  # lied
        ingestion_time=t,
        payload={"value": 1.0},
    )
    with pytest.raises(ValidationError, match="Backfilled"):
        catch_backfilled_equal_times(rec, lag=timedelta(days=3))


def test_planted_future_scored_sentiment_caught() -> None:
    bar = datetime(2022, 1, 1, tzinfo=UTC)
    scored = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ValidationError, match="Future-scored"):
        catch_future_scored_sentiment(scored_at=scored, bar_ts=bar, used_at_bar=True)


def test_planted_negative_lag_caught() -> None:
    t = datetime(2024, 1, 1, tzinfo=UTC)
    with pytest.raises(ValidationError, match="Negative publication lag"):
        catch_negative_lag(t, t - timedelta(hours=1))
