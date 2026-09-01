"""SyntheticNewsProvider integration tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl

from fmtrader.features.pipeline import build_features
from fmtrader.providers.alignment import align_feature
from fmtrader.providers.registry import ProviderRegistry
from fmtrader.providers.synthetic_news import SyntheticNewsProvider
from fmtrader.providers.technical import TechnicalProvider
from tests.helpers import ohlc_frame


class _Caps:
    has_volume = False
    has_spread = False
    has_open_interest = False


def test_deterministic_events_produce_deterministic_features() -> None:
    t0 = datetime(2021, 1, 4, 12, 0, tzinfo=UTC)
    bars = pl.DataFrame({"ts": [t0 + timedelta(minutes=i) for i in range(200)]})
    p = SyntheticNewsProvider(seed=42, n_events=30, publication_lag=timedelta(minutes=5))
    records = list(p.fetch("XAUUSD", t0, t0 + timedelta(minutes=199)))
    assert records  # non-empty
    records2 = list(p.fetch("XAUUSD", t0, t0 + timedelta(minutes=199)))
    assert [r.record_id for r in records] == [r.record_id for r in records2]
    assert [r.payload["polarity"] for r in records] == [r.payload["polarity"] for r in records2]

    spec = p.feature_specs()[0]
    s1 = align_feature(bars, records, spec)
    s2 = align_feature(bars, records2, spec)
    assert s1.to_list() == s2.to_list()


def test_feature_set_with_and_without_provider_differ_only_in_provider_columns() -> None:
    bars = ohlc_frame(180, seed=3)
    tech_only = {
        "name": "t",
        "version": "1",
        "features": [
            {"indicator": "atr", "params": {"period": 14}, "alias": "volatility_atr_14"},
        ],
    }
    with_news = {
        "name": "tn",
        "version": "1",
        "providers": [
            {"name": "technical", "required": True},
            {"name": "synthetic_news", "required": True},
        ],
        "features": [
            {
                "provider": "technical",
                "name": "atr",
                "params": {"period": 14},
                "alias": "volatility_atr_14",
            },
            {"provider": "synthetic_news", "name": "news_count_15m", "null_policy": "zero"},
        ],
    }
    reg = ProviderRegistry()
    reg.register(TechnicalProvider(caps=_Caps()))
    reg.register(SyntheticNewsProvider(seed=0, n_events=25))

    a = build_features(bars, tech_only, caps=_Caps(), dataset_id="t")
    b = build_features(bars, with_news, caps=_Caps(), dataset_id="t", provider_registry=reg)
    assert "volatility_atr_14" in a.columns and "volatility_atr_14" in b.columns
    assert "news_count_15m" in b.columns
    assert "news_count_15m" not in a.columns
    # Shared technical column should match (float32 path may differ at ~1e-6)
    import math

    for x, y in zip(
        a["volatility_atr_14"].to_list(), b["volatility_atr_14"].to_list(), strict=True
    ):
        if x is None and y is None:
            continue
        assert x is not None and y is not None
        assert math.isclose(float(x), float(y), rel_tol=1e-5, abs_tol=1e-5)
