"""Import all indicator modules so ``@register_indicator`` runs at import time."""

from fmtrader.features.indicators import (
    microstructure,
    momentum,
    session,
    trend,
    volatility,
    volume,
)

__all__ = [
    "microstructure",
    "momentum",
    "session",
    "trend",
    "volatility",
    "volume",
]
