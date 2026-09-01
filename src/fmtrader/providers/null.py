"""Null provider — registered but emits no records/features."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from fmtrader.providers.contracts import (
    DateRange,
    FeatureSpec,
    PointInTimeRecord,
    ProviderCapabilities,
    ProviderHealth,
)
from fmtrader.providers.protocol import FeatureProvider


class NullProvider(FeatureProvider):
    name = "null"
    kind = "alternative"
    optional = True

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(symbols="*", has_revisions=False)

    def availability(self, symbol: str) -> DateRange | None:
        return None

    def fetch(self, symbol: str, start: datetime, end: datetime) -> Iterable[PointInTimeRecord]:
        return []

    def feature_specs(self) -> list[FeatureSpec]:
        return []

    def health(self) -> ProviderHealth:
        return ProviderHealth(ok=True, detail="null provider", available=True)
