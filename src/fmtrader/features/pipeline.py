"""YAML-driven feature pipeline: validate → compute → store."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from fmtrader.core.errors import FeatureError
from fmtrader.data.catalog import Catalog, SnapshotManifest
from fmtrader.features import regime as _regime  # noqa: F401 — register regime indicator
from fmtrader.features.indicators import (  # noqa: F401 — populate registry
    microstructure,
    momentum,
    session,
    trend,
    volatility,
    volume,
)
from fmtrader.features.labeling import TripleBarrierConfig, meta_labels, triple_barrier_labels
from fmtrader.features.registry import (
    DatasetCapabilities,
    compute_indicator,
    get_indicator,
    list_indicators,
    validate_against_dataset,
)
from fmtrader.features.store import FeatureSetManifest, FeatureStore, definition_hash
from fmtrader.system.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class _Caps:
    has_volume: bool
    has_spread: bool
    has_open_interest: bool


def load_feature_set_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise FeatureError(f"Feature set YAML must be a mapping: {path}")
    for key in ("name", "version", "features"):
        if key not in data:
            raise FeatureError(f"Feature set YAML missing {key!r}: {path}")
    if not isinstance(data["features"], list):
        raise FeatureError("features must be a list")
    return data


def feature_set_definition_hash(definition: dict[str, Any]) -> str:
    """Hash the declarative definition (stable across key order)."""
    return definition_hash(definition)


def validate_feature_set(
    definition: dict[str, Any],
    caps: DatasetCapabilities,
    *,
    dataset_id: str,
) -> list[str]:
    """Fail fast before any computation; return list of output column aliases."""
    aliases: list[str] = []
    for i, item in enumerate(definition["features"]):
        if not isinstance(item, dict) or "indicator" not in item:
            raise FeatureError(f"features[{i}] must be a mapping with 'indicator'")
        name = str(item["indicator"])
        spec = get_indicator(name)
        validate_against_dataset(spec, caps, dataset_id=dataset_id)
        params = item.get("params") or {}
        if not isinstance(params, dict):
            raise FeatureError(f"features[{i}].params must be a mapping")
        alias = item.get("alias")
        if spec.multi_output:
            if alias:
                raise FeatureError(
                    f"features[{i}] ({name}) is multi-output; use column rename map, not alias"
                )
            cols = spec.output_columns or ()
            aliases.extend(f"{name}::{c}" for c in cols)
        else:
            aliases.append(str(alias) if alias else name)
    return aliases


def build_features(
    bars: pl.DataFrame,
    definition: dict[str, Any],
    *,
    caps: DatasetCapabilities,
    dataset_id: str,
    symbol: str = "XAUUSD",
    provider_registry: Any | None = None,
) -> pl.DataFrame:
    """Compute all features; assumes validation already passed.

    Legacy YAML (``indicator:``) uses the indicator registry directly.
    Provider-aware YAML (``provider:`` / ``providers:``) routes through the
    Phase 6 compose path. Core pipeline is unchanged when no providers are used.
    """
    uses_providers = bool(definition.get("providers")) or any(
        isinstance(x, dict) and "provider" in x for x in (definition.get("features") or [])
    )
    if uses_providers:
        from fmtrader.providers.compose import build_with_providers
        from fmtrader.providers.news_feed import NewsFeedProvider
        from fmtrader.providers.registry import ProviderRegistry, default_registry
        from fmtrader.providers.synthetic_news import SyntheticNewsProvider
        from fmtrader.providers.technical import TechnicalProvider

        reg: ProviderRegistry = provider_registry or default_registry()
        if not reg.has("technical") and not reg.is_disabled("technical"):
            reg.register(TechnicalProvider(caps=caps))
        if not reg.has("synthetic_news") and not reg.is_disabled("synthetic_news"):
            reg.register(SyntheticNewsProvider())
        if not reg.has("news_feed") and not reg.is_disabled("news_feed"):
            reg.register(NewsFeedProvider())
        return build_with_providers(
            bars,
            definition,
            registry=reg,
            caps=caps,
            dataset_id=dataset_id,
            symbol=symbol,
        )

    validate_feature_set(definition, caps, dataset_id=dataset_id)
    if "ts" not in bars.columns:
        raise FeatureError("bars frame missing ts")

    needed: set[str] = {"ts"}
    for item in definition["features"]:
        spec = get_indicator(str(item["indicator"]))
        needed.update(spec.requires)
    slim = bars.select([c for c in bars.columns if c in needed])
    # Prefer float32 inputs for large frames
    for col, dtype in zip(slim.columns, slim.dtypes, strict=True):
        if dtype == pl.Float64:
            slim = slim.with_columns(pl.col(col).cast(pl.Float32))

    out = slim.select("ts")
    for item in definition["features"]:
        name = str(item["indicator"])
        params = dict(item.get("params") or {})
        alias = item.get("alias")
        result = compute_indicator(name, slim, caps=caps, dataset_id=dataset_id, **params)
        if isinstance(result, pl.Series):
            s = result.rename(str(alias)) if alias else result
            if s.dtype == pl.Float64:
                s = s.cast(pl.Float32)
            out = out.with_columns(s)
        else:
            casted = result
            for col, dtype in zip(result.columns, result.dtypes, strict=True):
                if dtype == pl.Float64:
                    casted = casted.with_columns(pl.col(col).cast(pl.Float32))
            out = out.hstack(casted)
        del result

    labeling = definition.get("labeling")
    if isinstance(labeling, dict) and labeling.get("enabled", False):
        cfg = TripleBarrierConfig(
            atr_period=int(labeling.get("atr_period", 14)),
            pt_mult=float(labeling.get("pt_mult", 2.0)),
            sl_mult=float(labeling.get("sl_mult", 2.0)),
            max_horizon=int(labeling.get("max_horizon", 60)),
        )
        tb = triple_barrier_labels(slim, cfg)
        for col in tb.columns:
            if tb[col].dtype == pl.Float64:
                tb = tb.with_columns(pl.col(col).cast(pl.Float32))
        out = out.hstack(tb)
        primary = labeling.get("primary_side_column")
        if primary:
            if primary not in slim.columns:
                log.warning("meta_label_skipped_missing_primary", column=primary)
            else:
                out = out.with_columns(meta_labels(slim[primary], tb).cast(pl.Float32))

    return out


def build_and_store(
    *,
    dataset_id: str,
    feature_set_path: Path,
    catalog_root: Path,
    snapshots_dir: Path,
    features_root: Path,
) -> FeatureSetManifest:
    """Load dataset + YAML, validate, build, write feature store."""
    snap_path = snapshots_dir / f"{dataset_id}.json"
    if not snap_path.exists():
        raise FeatureError(f"Snapshot not found for dataset {dataset_id!r}: {snap_path}")
    manifest = SnapshotManifest.load(snap_path)
    caps = _Caps(
        has_volume=manifest.has_volume,
        has_spread=manifest.has_spread,
        has_open_interest=manifest.has_open_interest,
    )
    definition = load_feature_set_yaml(feature_set_path)
    def_hash = feature_set_definition_hash(definition)

    uses_providers = bool(definition.get("providers")) or any(
        isinstance(x, dict) and "provider" in x for x in (definition.get("features") or [])
    )

    # Fail before reading bars if gated
    if uses_providers:
        for key in ("name", "version", "features"):
            if key not in definition:
                raise FeatureError(f"Feature set YAML missing {key!r}")
    else:
        validate_feature_set(definition, caps, dataset_id=dataset_id)

    needed: set[str] = {"ts", "open", "high", "low", "close", "is_tradable"}
    if not uses_providers:
        for item in definition["features"]:
            needed.update(get_indicator(str(item["indicator"])).requires)
    else:
        for item in definition["features"]:
            if isinstance(item, dict) and item.get("provider") == "technical":
                needed.update(get_indicator(str(item["name"])).requires)
            elif isinstance(item, dict) and "indicator" in item:
                needed.update(get_indicator(str(item["indicator"])).requires)

    catalog = Catalog(catalog_root)
    bars = catalog.read(
        symbol=manifest.symbol,
        timeframe=manifest.timeframe,
        columns=sorted(c for c in needed if c),
    )

    t0 = time.perf_counter()
    import resource
    import sys

    frame = build_features(
        bars, definition, caps=caps, dataset_id=dataset_id, symbol=manifest.symbol
    )
    del bars
    elapsed = time.perf_counter() - t0
    # macOS: ru_maxrss is bytes; Linux: kilobytes
    maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_gb = maxrss / (1024**3) if sys.platform == "darwin" else maxrss / (1024**2)

    store = FeatureStore(features_root)
    version = str(definition["version"])
    name = str(definition["name"])
    written = store.write(
        frame,
        dataset_id=dataset_id,
        feature_set_name=name,
        feature_set_version=version,
        def_hash=def_hash,
        created_at=datetime.now(tz=UTC).isoformat(),
        peak_memory_gb=round(peak_gb, 3),
        elapsed_sec=round(elapsed, 3),
    )
    log.info(
        "feature_build_complete",
        dataset_id=dataset_id,
        version=version,
        rows=written.rows,
        cols=len(written.columns),
        elapsed_sec=written.elapsed_sec,
        peak_memory_gb=written.peak_memory_gb,
        definition_hash=def_hash,
    )
    return written


def availability_report(
    *,
    dataset_id: str,
    snapshots_dir: Path,
) -> list[dict[str, Any]]:
    """List registered indicators with available / reason against a dataset."""
    snap_path = snapshots_dir / f"{dataset_id}.json"
    if not snap_path.exists():
        raise FeatureError(f"Snapshot not found for dataset {dataset_id!r}")
    manifest = SnapshotManifest.load(snap_path)
    caps = _Caps(
        has_volume=manifest.has_volume,
        has_spread=manifest.has_spread,
        has_open_interest=manifest.has_open_interest,
    )
    rows: list[dict[str, Any]] = []
    for spec in list_indicators():
        try:
            validate_against_dataset(spec, caps, dataset_id=dataset_id)
            rows.append(
                {
                    "name": spec.name,
                    "category": spec.category,
                    "available": True,
                    "reason": "",
                }
            )
        except FeatureError as exc:
            rows.append(
                {
                    "name": spec.name,
                    "category": spec.category,
                    "available": False,
                    "reason": str(exc),
                }
            )
    return rows
