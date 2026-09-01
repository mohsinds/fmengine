"""Adapter package."""

from fmtrader.data.adapters.base import AdapterCapabilities, AdapterResult, MarketDataAdapter
from fmtrader.data.adapters.databento import DatabentoAdapter, parse_cme_symbol
from fmtrader.data.adapters.dukascopy import DukascopyAdapter
from fmtrader.data.adapters.registry import get_adapter

__all__ = [
    "AdapterCapabilities",
    "AdapterResult",
    "DatabentoAdapter",
    "DukascopyAdapter",
    "MarketDataAdapter",
    "get_adapter",
    "parse_cme_symbol",
]
