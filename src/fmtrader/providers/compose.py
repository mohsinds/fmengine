"""Compose providers into a feature frame."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import polars as pl
import yaml

from fmtrader.core.errors import FeatureError, ProviderError
from fmtrader.features.registry import DatasetCapabilities
from fmtrader.providers.alignment import align_feature
from fmtrader.providers.contracts import AlignmentStrategy, FeatureSpec
from fmtrader.providers.registry import ProviderRegistry
from fmtrader.providers.technical import TechnicalProvider


def _parse_duration(raw: str | int | float | timedelta) -> timedelta:
    if isinstance(raw, timedelta):
        return raw
    if isinstance(raw, (int, float)):
        return timedelta(seconds=float(raw))
    s = str(raw).strip().lower()
    if s.endswith("ms"):
        return timedelta(milliseconds=float(s[:-2]))
    if s.endswith("s") and not s.endswith("ms"):
        return timedelta(seconds=float(s[:-1]))
    if s.endswith("m"):
        return timedelta(minutes=float(s[:-1]))
    if s.endswith("h"):
        return timedelta(hours=float(s[:-1]))
    if s.endswith("d"):
        return timedelta(days=float(s[:-1]))
    raise ProviderError(f"Cannot parse duration: {raw!r}")


def parse_alignment(raw: dict[str, Any] | None) -> AlignmentStrategy:
    if not raw:
        return AlignmentStrategy(strategy="last_known")
    data = dict(raw)
    if "half_life" in data:
        data["half_life"] = _parse_duration(data["half_life"])
    if "window" in data:
        data["window"] = _parse_duration(data["window"])
    return AlignmentStrategy.model_validate(data)


def build_with_providers(
    bars: pl.DataFrame,
    definition: dict[str, Any],
    *,
    registry: ProviderRegistry,
    caps: DatasetCapabilities,
    dataset_id: str,
    symbol: str = "XAUUSD",
) -> pl.DataFrame:
    """Build features from a provider-aware feature-set definition.

    Supports:
    - Legacy items: ``{indicator: sma, params: ..., alias: ...}`` via technical
    - Provider items: ``{provider: synthetic_news, name: news_count_15m, alignment: ...}``
    """
    features = definition.get("features") or []
    if not isinstance(features, list):
        raise FeatureError("features must be a list")

    provider_cfg = {
        str(p["name"]): p
        for p in (definition.get("providers") or [])
        if isinstance(p, dict) and "name" in p
    }

    # Validate absent providers before any compute
    reqs = []
    for item in features:
        if isinstance(item, dict) and "provider" in item:
            reqs.append(item)
    required_names = {
        str(p["name"])
        for p in (definition.get("providers") or [])
        if isinstance(p, dict) and p.get("required", True)
    }
    registry.validate_feature_requests(reqs, required_providers=required_names)

    out = bars.select("ts")
    tech = TechnicalProvider(caps=caps)
    # Ensure technical is usable even if not pre-registered
    if not registry.has("technical"):
        registry.register(tech)

    for i, item in enumerate(features):
        if not isinstance(item, dict):
            raise FeatureError(f"features[{i}] must be a mapping")

        # Legacy indicator path
        if "indicator" in item:
            name = str(item["indicator"])
            params = dict(item.get("params") or {})
            alias = item.get("alias")
            frame = tech.compute_from_bars(
                bars,
                feature_names=[name],
                params_by_name={name: params},
                caps=caps,
                dataset_id=dataset_id,
                aliases={name: str(alias)} if alias else None,
            )
            cols = [c for c in frame.columns if c != "ts"]
            out = out.hstack(frame.select(cols))
            continue

        pname = str(item.get("provider", ""))
        fname = str(item.get("name") or item.get("feature") or "")
        if not pname or not fname:
            raise FeatureError(f"features[{i}] needs provider+name or indicator")

        provider = registry.get(pname)
        safety_lag = timedelta(0)
        pcfg = provider_cfg.get(pname) or {}
        if "safety_lag" in pcfg:
            safety_lag = _parse_duration(pcfg["safety_lag"])

        if pname == "technical":
            params = dict(item.get("params") or {})
            alias = item.get("alias")
            frame = tech.compute_from_bars(
                bars,
                feature_names=[fname],
                params_by_name={fname: params},
                caps=caps,
                dataset_id=dataset_id,
                aliases={fname: str(alias)} if alias else {fname: fname},
            )
            cols = [c for c in frame.columns if c != "ts"]
            out = out.hstack(frame.select(cols))
            continue

        # External PIT provider
        start = bars["ts"].min()
        end = bars["ts"].max()
        assert isinstance(start, datetime) and isinstance(end, datetime)
        records = list(provider.fetch(symbol, start, end))
        # Match named feature spec or build from YAML alignment
        specs = {s.name: s for s in provider.feature_specs()}
        if fname in specs and "alignment" not in item:
            spec = specs[fname]
        else:
            alignment = parse_alignment(item.get("alignment"))
            null_policy = item.get(
                "null_policy", specs[fname].null_policy if fname in specs else "zero"
            )
            spec = FeatureSpec(
                name=str(item.get("alias") or fname),
                alignment=alignment,
                null_policy=null_policy,
            )
        series = align_feature(bars, records, spec, safety_lag=safety_lag)
        if series.dtype == pl.Float64:
            series = series.cast(pl.Float32)
        out = out.with_columns(series)

    return out


def load_provider_feature_set(path: str | Any) -> dict[str, Any]:
    from pathlib import Path

    p = Path(path)
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise FeatureError(f"Feature set YAML must be a mapping: {p}")
    return data
