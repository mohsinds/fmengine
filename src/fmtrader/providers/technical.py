"""TechnicalProvider — wraps the indicator registry in the FeatureProvider protocol."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta

import polars as pl

from fmtrader.core.errors import FeatureError, ProviderError
from fmtrader.features.registry import (
    DatasetCapabilities,
    compute_indicator,
    get_indicator,
    list_indicators,
)
from fmtrader.providers.contracts import (
    AlignmentStrategy,
    DateRange,
    FeatureSpec,
    PointInTimeRecord,
    ProviderCapabilities,
    ProviderHealth,
)
from fmtrader.providers.protocol import FeatureProvider


class TechnicalProvider(FeatureProvider):
    """Dense bar-derived features via the existing indicator registry."""

    name = "technical"
    kind = "technical"
    optional = False

    def __init__(self, caps: DatasetCapabilities | None = None) -> None:
        self._caps = caps

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            symbols="*",
            asset_classes=["*"],
            min_granularity="1m",
            has_revisions=False,
            typical_publication_lag=timedelta(0),
            requires_credentials=False,
        )

    def availability(self, symbol: str) -> DateRange | None:
        return DateRange(
            start=datetime(1970, 1, 1),
            end=datetime(2100, 1, 1),
        )

    def fetch(self, symbol: str, start: datetime, end: datetime) -> Iterable[PointInTimeRecord]:
        # Technical features are computed from bars, not PIT records.
        return []

    def feature_specs(self) -> list[FeatureSpec]:
        specs: list[FeatureSpec] = []
        for ind in list_indicators():
            specs.append(
                FeatureSpec(
                    name=ind.name,
                    dtype="float",
                    alignment=AlignmentStrategy(strategy="last_known"),
                    lookback_required=timedelta(minutes=max(ind.min_lookback({}), 1)),
                    null_policy="null",
                )
            )
        return specs

    def health(self) -> ProviderHealth:
        return ProviderHealth(ok=True, detail="indicator registry", available=True)

    def compute_from_bars(
        self,
        bars: pl.DataFrame,
        *,
        feature_names: Sequence[str],
        params_by_name: dict[str, dict[str, object]] | None = None,
        caps: DatasetCapabilities | None = None,
        dataset_id: str = "unknown",
        aliases: dict[str, str] | None = None,
    ) -> pl.DataFrame:
        caps = caps or self._caps
        if caps is None:
            raise ProviderError("TechnicalProvider requires dataset capabilities")
        params_by_name = params_by_name or {}
        aliases = aliases or {}
        out = bars.select("ts") if "ts" in bars.columns else pl.DataFrame({"ts": []})
        for name in feature_names:
            try:
                get_indicator(name)
            except FeatureError as exc:
                raise ProviderError(str(exc)) from exc
            params = dict(params_by_name.get(name) or {})
            result = compute_indicator(name, bars, caps=caps, dataset_id=dataset_id, **params)
            alias = aliases.get(name)
            if isinstance(result, pl.Series):
                s = result.rename(alias) if alias else result
                if s.dtype == pl.Float64:
                    s = s.cast(pl.Float32)
                out = out.with_columns(s)
            else:
                casted = result
                for col, dtype in zip(result.columns, result.dtypes, strict=True):
                    if dtype == pl.Float64:
                        casted = casted.with_columns(pl.col(col).cast(pl.Float32))
                out = out.hstack(casted)
        return out
