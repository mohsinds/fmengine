"""Vendor adapter protocol and capability declarations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import polars as pl

from fmtrader.core.enums import InstrumentClass, Side


@dataclass(frozen=True)
class AdapterCapabilities:
    """What a vendor feed can provide — gates downstream features."""

    has_volume: bool
    has_spread: bool
    has_open_interest: bool
    has_depth: bool
    session_calendar: str  # registry key, e.g. "xauusd_fx"
    source: str


@dataclass(frozen=True)
class AdapterResult:
    """Normalized frame plus capability metadata from an adapter."""

    frame: pl.DataFrame
    capabilities: AdapterCapabilities
    side: Side | None


class MarketDataAdapter(Protocol):
    """Read a vendor file into the canonical bar column set."""

    name: str

    def capabilities(self) -> AdapterCapabilities: ...

    def read(
        self,
        path: Path,
        *,
        symbol: str,
        timeframe: str,
        instrument_class: InstrumentClass,
        side: Side | None = None,
    ) -> AdapterResult: ...


# Canonical column order for bulk frames (before quality adds is_tradable).
CANONICAL_COLUMNS: tuple[str, ...] = (
    "ts",
    "symbol",
    "instrument_class",
    "timeframe",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "open_interest",
    "bid",
    "ask",
)
