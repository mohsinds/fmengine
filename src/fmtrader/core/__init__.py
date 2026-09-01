"""Domain enums, contracts, and errors.

Invariant: this package must not import from any other ``fmtrader.*`` package
outside ``fmtrader.core``.
"""

from fmtrader.core.contracts import Bar
from fmtrader.core.enums import InstrumentClass, Side
from fmtrader.core.errors import (
    AdapterError,
    ContractError,
    DataError,
    FmtraderError,
    QualityError,
    SettingsError,
)

__all__ = [
    "AdapterError",
    "Bar",
    "ContractError",
    "DataError",
    "FmtraderError",
    "InstrumentClass",
    "QualityError",
    "SettingsError",
    "Side",
]
