"""Adapter package."""

from fmtrader.data.adapters.base import AdapterCapabilities, AdapterResult, MarketDataAdapter
from fmtrader.data.adapters.dukascopy import DukascopyAdapter, get_adapter

__all__ = [
    "AdapterCapabilities",
    "AdapterResult",
    "DukascopyAdapter",
    "MarketDataAdapter",
    "get_adapter",
]
