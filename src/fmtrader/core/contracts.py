"""Canonical bar contract.

``ts`` is the bar **OPEN** time, always timezone-aware UTC. Naive datetimes are rejected.
Optional fields default to ``None`` (never coerced to zero).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from fmtrader.core.enums import InstrumentClass
from fmtrader.core.errors import ContractError

InstrumentClassLiteral = Literal[
    "spot_cfd",
    "futures_raw",
    "futures_continuous",
    "equity",
    "crypto",
]


class Bar(BaseModel):
    """One OHLCV bar in the canonical schema."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ts: datetime
    symbol: str
    instrument_class: InstrumentClass
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    open_interest: float | None = None
    bid: float | None = None
    ask: float | None = None

    @field_validator("ts")
    @classmethod
    def _require_tz_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ContractError("Bar.ts must be timezone-aware UTC (naive datetime rejected)")
        return value.astimezone(UTC)

    @field_validator("symbol")
    @classmethod
    def _nonempty_symbol(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ContractError("Bar.symbol must be non-empty")
        return cleaned

    @field_validator("timeframe")
    @classmethod
    def _nonempty_timeframe(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ContractError("Bar.timeframe must be non-empty")
        return cleaned

    @model_validator(mode="after")
    def _ohlc_invariants(self) -> Bar:
        for name, val in (
            ("open", self.open),
            ("high", self.high),
            ("low", self.low),
            ("close", self.close),
        ):
            if val <= 0:
                raise ContractError(f"Bar.{name} must be > 0 (got {val})")
        if self.low > min(self.open, self.close):
            raise ContractError(
                f"OHLC violation: low ({self.low}) > min(open, close) "
                f"({min(self.open, self.close)})"
            )
        if self.high < max(self.open, self.close):
            raise ContractError(
                f"OHLC violation: high ({self.high}) < max(open, close) "
                f"({max(self.open, self.close)})"
            )
        return self
