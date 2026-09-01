"""Provider protocol and registry tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fmtrader.core.errors import ProviderError
from fmtrader.features.pipeline import build_features
from fmtrader.providers.null import NullProvider
from fmtrader.providers.optional_gated import OptionalDependencyProvider
from fmtrader.providers.registry import ProviderRegistry, reset_registry
from fmtrader.providers.synthetic_news import SyntheticNewsProvider
from fmtrader.providers.technical import TechnicalProvider
from tests.helpers import ohlc_frame


class _Caps:
    has_volume = False
    has_spread = False
    has_open_interest = False


def test_provider_declares_capabilities() -> None:
    p = SyntheticNewsProvider()
    caps = p.capabilities()
    assert caps.has_revisions is True
    assert caps.typical_publication_lag > timedelta(0)
    specs = p.feature_specs()
    assert any(s.name == "news_count_15m" for s in specs)


def test_core_pipeline_runs_with_zero_providers_registered() -> None:
    reset_registry()
    bars = ohlc_frame(120, seed=1)
    definition = {
        "name": "tech_only",
        "version": "1",
        "features": [
            {"indicator": "atr", "params": {"period": 14}, "alias": "volatility_atr_14"},
            {"indicator": "rsi", "params": {"period": 14}, "alias": "momentum_rsi_14"},
        ],
    }
    out = build_features(bars, definition, caps=_Caps(), dataset_id="test")
    assert "volatility_atr_14" in out.columns
    assert "momentum_rsi_14" in out.columns
    assert out.height == bars.height


def test_missing_optional_dependency_disables_provider_without_crashing() -> None:
    reg = ProviderRegistry()
    reg.register(OptionalDependencyProvider(module_name="definitely_not_installed_xyz_123"))
    assert reg.is_disabled("optional_gated")
    assert "missing" in (reg.disable_reason("optional_gated") or "").lower()
    statuses = reg.list_status()
    assert any(not s.available for s in statuses)


def test_missing_credential_disables_provider_cleanly() -> None:
    reg = ProviderRegistry()
    reg.register(
        OptionalDependencyProvider(
            module_name="math",
            require_credential=True,
            credential=None,
        )
    )
    assert reg.is_disabled("optional_gated")


def test_feature_set_requesting_absent_provider_fails_before_computation() -> None:
    reg = ProviderRegistry()
    reg.register(TechnicalProvider(caps=_Caps()))
    with pytest.raises(ProviderError, match="absent provider"):
        reg.validate_feature_requests(
            [{"provider": "news_rss", "name": "sentiment"}],
            required_providers={"news_rss"},
        )


def test_null_provider_registers() -> None:
    reg = ProviderRegistry()
    reg.register(NullProvider())
    assert reg.has("null")
    assert list(reg.get("null").fetch("X", datetime.now(tz=UTC), datetime.now(tz=UTC))) == []
