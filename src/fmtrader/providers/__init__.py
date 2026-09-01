"""Provider framework — point-in-time external features."""

from __future__ import annotations

from fmtrader.providers.contracts import (
    AlignmentStrategy,
    FeatureSpec,
    PointInTimeRecord,
    ProviderCapabilities,
    ProviderHealth,
)
from fmtrader.providers.registry import (
    ProviderRegistry,
    default_registry,
    get_provider,
    register_provider,
    reset_registry,
)

__all__ = [
    "AlignmentStrategy",
    "FeatureSpec",
    "PointInTimeRecord",
    "ProviderCapabilities",
    "ProviderHealth",
    "ProviderRegistry",
    "default_registry",
    "get_provider",
    "register_provider",
    "reset_registry",
]
