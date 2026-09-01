"""Adapter registry."""

from __future__ import annotations

from fmtrader.core.errors import AdapterError
from fmtrader.data.adapters.base import MarketDataAdapter
from fmtrader.data.adapters.databento import DatabentoAdapter
from fmtrader.data.adapters.dukascopy import DukascopyAdapter


def get_adapter(name: str) -> MarketDataAdapter:
    """Resolve an adapter by CLI name."""
    key = name.strip().lower()
    if key == "dukascopy":
        return DukascopyAdapter()
    if key in {"databento", "dbn"}:
        return DatabentoAdapter()
    raise AdapterError(f"Unknown adapter: {name}")
