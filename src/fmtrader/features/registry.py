"""Indicator registry with capability declarations and dataset gating."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import polars as pl
from pydantic import BaseModel

from fmtrader.core.errors import FeatureError


@runtime_checkable
class DatasetCapabilities(Protocol):
    """Minimal capability surface used for gating (catalog manifest / adapter)."""

    @property
    def has_volume(self) -> bool: ...

    @property
    def has_spread(self) -> bool: ...

    @property
    def has_open_interest(self) -> bool: ...


@dataclass(frozen=True)
class IndicatorSpec:
    """Registered indicator metadata."""

    name: str
    category: str
    func: Callable[..., pl.Series | pl.DataFrame]
    requires: tuple[str, ...]
    requires_volume: bool
    requires_spread: bool
    requires_open_interest: bool
    min_lookback: Callable[[Mapping[str, Any]], int]
    params_schema: type[BaseModel] | None
    multi_output: bool
    output_columns: tuple[str, ...] | None


_REGISTRY: dict[str, IndicatorSpec] = {}


def register_indicator(
    *,
    name: str,
    category: str,
    requires: Sequence[str] = ("close",),
    requires_volume: bool = False,
    requires_spread: bool = False,
    requires_open_interest: bool = False,
    min_lookback: Callable[[Mapping[str, Any]], int] | int = 1,
    params_schema: type[BaseModel] | None = None,
    multi_output: bool = False,
    output_columns: Sequence[str] | None = None,
) -> Callable[[Callable[..., pl.Series | pl.DataFrame]], Callable[..., pl.Series | pl.DataFrame]]:
    """Decorator that registers a pure indicator function."""

    def decorator(
        fn: Callable[..., pl.Series | pl.DataFrame],
    ) -> Callable[..., pl.Series | pl.DataFrame]:
        lookback_fn: Callable[[Mapping[str, Any]], int]
        if isinstance(min_lookback, int):
            n = min_lookback

            def lookback_fn(_p: Mapping[str, Any], *, _n: int = n) -> int:
                return _n
        else:
            lookback_fn = min_lookback

        if name in _REGISTRY:
            raise FeatureError(f"Duplicate indicator registration: {name}")

        _REGISTRY[name] = IndicatorSpec(
            name=name,
            category=category,
            func=fn,
            requires=tuple(requires),
            requires_volume=requires_volume,
            requires_spread=requires_spread,
            requires_open_interest=requires_open_interest,
            min_lookback=lookback_fn,
            params_schema=params_schema,
            multi_output=multi_output,
            output_columns=tuple(output_columns) if output_columns else None,
        )
        return fn

    return decorator


def get_indicator(name: str) -> IndicatorSpec:
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        known = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise FeatureError(f"Unknown indicator {name!r}. Known: {known}") from exc


def list_indicators(*, category: str | None = None) -> list[IndicatorSpec]:
    specs = sorted(_REGISTRY.values(), key=lambda s: (s.category, s.name))
    if category is None:
        return specs
    return [s for s in specs if s.category == category]


def clear_registry() -> None:
    """Tests only — wipe registrations."""
    _REGISTRY.clear()


def validate_against_dataset(
    spec: IndicatorSpec,
    caps: DatasetCapabilities,
    *,
    dataset_id: str | None = None,
) -> None:
    """Raise ``FeatureError`` naming dataset + capability when gated off."""
    ds = dataset_id or "unknown_dataset"
    if spec.requires_volume and not caps.has_volume:
        raise FeatureError(
            f"Indicator {spec.name!r} requires volume, but dataset {ds!r} has has_volume=false"
        )
    if spec.requires_spread and not caps.has_spread:
        raise FeatureError(
            f"Indicator {spec.name!r} requires spread, but dataset {ds!r} has has_spread=false"
        )
    if spec.requires_open_interest and not caps.has_open_interest:
        raise FeatureError(
            f"Indicator {spec.name!r} requires open_interest, but dataset {ds!r} has "
            f"has_open_interest=false"
        )


def compute_indicator(
    name: str,
    frame: pl.DataFrame,
    *,
    caps: DatasetCapabilities | None = None,
    dataset_id: str | None = None,
    **params: Any,
) -> pl.Series | pl.DataFrame:
    """Validate capabilities/columns/lookback, then compute ``name``."""
    spec = get_indicator(name)
    if caps is not None:
        validate_against_dataset(spec, caps, dataset_id=dataset_id)

    missing = [c for c in spec.requires if c not in frame.columns]
    if missing:
        raise FeatureError(f"Indicator {name!r} missing columns: {missing}")

    validated: dict[str, Any] = dict(params)
    if spec.params_schema is not None:
        validated = spec.params_schema(**params).model_dump()

    need = spec.min_lookback(validated)
    if frame.height < need:
        raise FeatureError(f"Indicator {name!r} needs min_lookback={need} rows, got {frame.height}")

    return spec.func(frame, **validated)
