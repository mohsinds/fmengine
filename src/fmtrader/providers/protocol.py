"""FeatureProvider protocol / base."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from datetime import datetime

import polars as pl

from fmtrader.providers.contracts import (
    DateRange,
    FeatureSpec,
    PointInTimeRecord,
    ProviderCapabilities,
    ProviderHealth,
    ProviderKind,
)


class FeatureProvider(ABC):
    """Every feature source — technical or external — implements this."""

    name: str
    kind: ProviderKind
    optional: bool

    @abstractmethod
    def capabilities(self) -> ProviderCapabilities: ...

    @abstractmethod
    def availability(self, symbol: str) -> DateRange | None: ...

    @abstractmethod
    def fetch(self, symbol: str, start: datetime, end: datetime) -> Iterable[PointInTimeRecord]: ...

    @abstractmethod
    def feature_specs(self) -> list[FeatureSpec]: ...

    @abstractmethod
    def health(self) -> ProviderHealth: ...


class BarFeatureProvider(ABC):
    """Providers that compute dense features directly from bars (technical)."""

    @abstractmethod
    def compute_from_bars(
        self,
        bars: pl.DataFrame,
        *,
        feature_names: Sequence[str],
        params_by_name: dict[str, dict[str, object]] | None = None,
    ) -> pl.DataFrame: ...
