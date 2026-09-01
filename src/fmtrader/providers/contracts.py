"""Point-in-time contracts and feature specs for external providers."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from fmtrader.core.errors import ProviderError

ProviderKind = Literal["technical", "sentiment", "news", "fundamental", "macro", "alternative"]
FeatureDtype = Literal["float", "int", "bool", "category"]
NullPolicy = Literal["null", "zero", "last_known", "fail"]
AlignmentName = Literal[
    "last_known",
    "decay",
    "window_agg",
    "count",
    "since_last",
    "impulse",
    "scheduled_proximity",
]


class PointInTimeRecord(BaseModel):
    """External record with the three-timestamp contract.

    Rule: a record may influence bar ``t`` iff ``available_time <= t``.
    Never join on ``event_time`` or ``ingestion_time``.
    """

    record_id: str
    event_time: datetime
    available_time: datetime
    ingestion_time: datetime
    revision_of: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_times(self) -> PointInTimeRecord:
        if self.available_time < self.event_time:
            raise ProviderError(
                f"available_time ({self.available_time}) must not precede "
                f"event_time ({self.event_time})"
            )
        return self


class AlignmentStrategy(BaseModel):
    """How sparse PIT records become dense bar-aligned features."""

    strategy: AlignmentName
    half_life: timedelta | None = None
    window: timedelta | None = None
    agg: Literal["mean", "sum", "std", "min", "max", "last"] | None = None
    unit: Literal["seconds", "minutes", "hours"] = "minutes"
    value_field: str = "value"

    @model_validator(mode="after")
    def _check_params(self) -> AlignmentStrategy:
        if self.strategy == "decay" and self.half_life is None:
            raise ProviderError("decay alignment requires half_life")
        if self.strategy in {"window_agg", "count"} and self.window is None:
            raise ProviderError(f"{self.strategy} alignment requires window")
        if self.strategy == "window_agg" and self.agg is None:
            raise ProviderError("window_agg requires agg")
        return self


class FeatureSpec(BaseModel):
    name: str
    dtype: FeatureDtype = "float"
    alignment: AlignmentStrategy
    lookback_required: timedelta = timedelta(0)
    null_policy: NullPolicy = "null"


class RateLimit(BaseModel):
    requests_per_minute: int
    burst: int | None = None


class ProviderCapabilities(BaseModel):
    symbols: list[str] | Literal["*"] = "*"
    asset_classes: list[str] = Field(default_factory=lambda: ["*"])
    min_granularity: str = "1m"
    has_revisions: bool = False
    typical_publication_lag: timedelta = timedelta(0)
    requires_credentials: bool = False
    rate_limit: RateLimit | None = None
    # When True, reject records with available_time == event_time
    enforce_nonzero_lag: bool = False


class ProviderHealth(BaseModel):
    ok: bool
    detail: str = ""
    available: bool = True
    disable_reason: str | None = None


class DateRange(BaseModel):
    start: datetime
    end: datetime
