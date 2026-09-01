"""Provider registry with optional-dependency isolation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fmtrader.core.errors import ProviderError
from fmtrader.providers.protocol import FeatureProvider

_REGISTRY: dict[str, FeatureProvider] = {}
_DISABLED: dict[str, str] = {}


@dataclass
class ProviderStatus:
    name: str
    kind: str
    optional: bool
    registered: bool
    available: bool
    reason: str = ""
    health_ok: bool = True


@dataclass
class ProviderRegistry:
    """Config-driven composition of feature providers."""

    _providers: dict[str, FeatureProvider] = field(default_factory=dict)
    _disabled: dict[str, str] = field(default_factory=dict)
    _disabled_meta: dict[str, dict[str, object]] = field(default_factory=dict)

    def register(self, provider: FeatureProvider) -> None:
        health = provider.health()
        if not health.available:
            self._disabled[provider.name] = health.disable_reason or health.detail or "unavailable"
            self._disabled_meta[provider.name] = {
                "kind": str(provider.kind),
                "optional": bool(provider.optional),
            }
            return
        if provider.name in self._providers:
            raise ProviderError(f"Duplicate provider registration: {provider.name}")
        self._providers[provider.name] = provider

    def get(self, name: str) -> FeatureProvider:
        if name in self._disabled:
            raise ProviderError(f"Provider {name!r} is disabled: {self._disabled[name]}")
        try:
            return self._providers[name]
        except KeyError as exc:
            known = ", ".join(sorted(self._providers)) or "(none)"
            raise ProviderError(f"Unknown provider {name!r}. Known: {known}") from exc

    def has(self, name: str) -> bool:
        return name in self._providers

    def is_disabled(self, name: str) -> bool:
        return name in self._disabled

    def disable_reason(self, name: str) -> str | None:
        return self._disabled.get(name)

    def list_status(self) -> list[ProviderStatus]:
        rows: list[ProviderStatus] = []
        for name, p in sorted(self._providers.items()):
            h = p.health()
            rows.append(
                ProviderStatus(
                    name=name,
                    kind=str(p.kind),
                    optional=bool(p.optional),
                    registered=True,
                    available=True,
                    reason="",
                    health_ok=h.ok,
                )
            )
        for name, reason in sorted(self._disabled.items()):
            meta = self._disabled_meta.get(name, {})
            rows.append(
                ProviderStatus(
                    name=name,
                    kind=str(meta.get("kind", "?")),
                    optional=bool(meta.get("optional", True)),
                    registered=False,
                    available=False,
                    reason=reason,
                    health_ok=False,
                )
            )
        return rows

    def validate_feature_requests(
        self,
        requests: list[dict[str, Any]],
        *,
        required_providers: set[str] | None = None,
    ) -> None:
        """Fail before computation if a named provider is absent or disabled."""
        required_providers = required_providers or set()
        for i, req in enumerate(requests):
            pname = str(req.get("provider", ""))
            if not pname:
                continue
            if pname in required_providers or req.get("required", True):
                if self.is_disabled(pname):
                    raise ProviderError(
                        f"features[{i}] requires provider {pname!r} which is disabled: "
                        f"{self.disable_reason(pname)}"
                    )
                if not self.has(pname):
                    raise ProviderError(
                        f"features[{i}] names absent provider {pname!r}; "
                        "register it or remove the feature before computation starts"
                    )


# Process-global default registry
_DEFAULT = ProviderRegistry()


def default_registry() -> ProviderRegistry:
    return _DEFAULT


def reset_registry() -> None:
    """Tests only."""
    global _DEFAULT
    _DEFAULT = ProviderRegistry()
    _REGISTRY.clear()
    _DISABLED.clear()


def register_provider(
    provider: FeatureProvider, *, registry: ProviderRegistry | None = None
) -> None:
    (registry or default_registry()).register(provider)


def get_provider(name: str, *, registry: ProviderRegistry | None = None) -> FeatureProvider:
    return (registry or default_registry()).get(name)
