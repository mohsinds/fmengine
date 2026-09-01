"""Optional provider that disables cleanly when a dependency/credential is missing."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from importlib import import_module

from fmtrader.providers.contracts import (
    DateRange,
    FeatureSpec,
    PointInTimeRecord,
    ProviderCapabilities,
    ProviderHealth,
)
from fmtrader.providers.protocol import FeatureProvider


class OptionalDependencyProvider(FeatureProvider):
    """Reference optional provider for testing missing-dep isolation.

    Attempts to import ``module_name``; on failure reports unavailable rather
    than raising during registration.
    """

    name = "optional_gated"
    kind = "alternative"
    optional = True

    def __init__(
        self,
        *,
        module_name: str = "fmtrader_nonexistent_vendor_xyz",
        credential: str | None = None,
        require_credential: bool = False,
    ) -> None:
        self.module_name = module_name
        self.credential = credential
        self.require_credential = require_credential
        self._import_error: str | None = None
        try:
            import_module(module_name)
        except ImportError as exc:
            self._import_error = str(exc)

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(requires_credentials=self.require_credential)

    def availability(self, symbol: str) -> DateRange | None:
        return None

    def fetch(self, symbol: str, start: datetime, end: datetime) -> Iterable[PointInTimeRecord]:
        return []

    def feature_specs(self) -> list[FeatureSpec]:
        return []

    def health(self) -> ProviderHealth:
        if self._import_error is not None:
            return ProviderHealth(
                ok=False,
                available=False,
                detail="missing dependency",
                disable_reason=f"optional dependency missing: {self._import_error}",
            )
        if self.require_credential and not self.credential:
            return ProviderHealth(
                ok=False,
                available=False,
                detail="missing credential",
                disable_reason="optional credential missing",
            )
        return ProviderHealth(ok=True, available=True, detail="ready")
