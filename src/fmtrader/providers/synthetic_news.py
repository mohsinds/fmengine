"""Deterministic synthetic news provider for join-semantics testing."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from fmtrader.providers.contracts import (
    AlignmentStrategy,
    DateRange,
    FeatureSpec,
    PointInTimeRecord,
    ProviderCapabilities,
    ProviderHealth,
)
from fmtrader.providers.protocol import FeatureProvider


class SyntheticNewsProvider(FeatureProvider):
    """Emits deterministic fake news/sentiment events — no real vendor."""

    name = "synthetic_news"
    kind = "news"
    optional = True

    def __init__(
        self,
        *,
        seed: int = 0,
        n_events: int = 20,
        publication_lag: timedelta = timedelta(minutes=5),
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> None:
        self.seed = seed
        self.n_events = n_events
        self.publication_lag = publication_lag
        self._start = start or datetime(2021, 1, 4, 12, 0, tzinfo=UTC)
        self._end = end or datetime(2021, 1, 5, 12, 0, tzinfo=UTC)

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            symbols="*",
            asset_classes=["fx", "cfd", "metal"],
            min_granularity="1m",
            has_revisions=True,
            typical_publication_lag=self.publication_lag,
            requires_credentials=False,
            enforce_nonzero_lag=True,
        )

    def availability(self, symbol: str) -> DateRange | None:
        return DateRange(start=self._start, end=self._end)

    def fetch(self, symbol: str, start: datetime, end: datetime) -> Iterable[PointInTimeRecord]:
        # Span the requested window so features are non-trivial on real datasets
        win_start = start if start.tzinfo else start.replace(tzinfo=UTC)
        win_end = end if end.tzinfo else end.replace(tzinfo=UTC)
        if win_end <= win_start:
            return []
        span = (win_end - win_start).total_seconds()
        records: list[PointInTimeRecord] = []
        for i in range(self.n_events):
            digest = sha256(
                f"{self.seed}:{symbol}:{i}:{win_start.isoformat()}".encode()
            ).hexdigest()
            frac = int(digest[:8], 16) / 0xFFFFFFFF
            event_t = win_start + timedelta(seconds=frac * span)
            avail_t = event_t + self.publication_lag
            if avail_t > win_end:
                continue
            polarity = (int(digest[8:16], 16) / 0xFFFFFFFF) * 2.0 - 1.0
            records.append(
                PointInTimeRecord(
                    record_id=f"syn-{self.seed}-{i}",
                    event_time=event_t,
                    available_time=avail_t,
                    ingestion_time=avail_t + timedelta(seconds=1),
                    payload={
                        "headline": f"Synthetic event {i}",
                        "polarity": polarity,
                        "value": polarity,
                        "relevance": 0.8,
                        "source": "synthetic",
                        "symbols": [symbol],
                    },
                )
            )
        return records

    def feature_specs(self) -> list[FeatureSpec]:
        return [
            FeatureSpec(
                name="sentiment_polarity_last",
                dtype="float",
                alignment=AlignmentStrategy(strategy="last_known", value_field="polarity"),
                null_policy="zero",
            ),
            FeatureSpec(
                name="sentiment_polarity_ewm_60m",
                dtype="float",
                alignment=AlignmentStrategy(
                    strategy="decay",
                    half_life=timedelta(minutes=60),
                    value_field="polarity",
                ),
                null_policy="zero",
            ),
            FeatureSpec(
                name="news_count_15m",
                dtype="float",
                alignment=AlignmentStrategy(
                    strategy="count",
                    window=timedelta(minutes=15),
                    value_field="polarity",
                ),
                null_policy="zero",
            ),
        ]

    def health(self) -> ProviderHealth:
        return ProviderHealth(ok=True, detail="synthetic deterministic", available=True)
