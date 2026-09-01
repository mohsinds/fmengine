"""Strategy protocol and registry."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

import polars as pl
from pydantic import BaseModel

from fmtrader.core.errors import FeatureError


@runtime_checkable
class Strategy(Protocol):
    """Strategies emit integer positions: -1 / 0 / +1 per bar (signal at bar open decision).

    The backtest harness shifts fills to the *next* bar — strategies must not bake that in.
    """

    name: str

    def generate(self, bars: pl.DataFrame, params: Mapping[str, Any]) -> pl.Series:
        """Return a Series named ``position`` aligned to ``bars`` (desired position after signal)."""
        ...


_REGISTRY: dict[str, type] = {}


def register_strategy(cls: type) -> type:
    name = getattr(cls, "name", None)
    if not isinstance(name, str) or not name:
        raise FeatureError("Strategy class must define string name")
    if name in _REGISTRY:
        raise FeatureError(f"Duplicate strategy: {name}")
    _REGISTRY[name] = cls
    return cls


def get_strategy(name: str) -> Strategy:
    try:
        cls = _REGISTRY[name]
    except KeyError as exc:
        raise FeatureError(f"Unknown strategy {name!r}. Known: {sorted(_REGISTRY)}") from exc
    instance: Strategy = cls()
    return instance


def list_strategies() -> list[str]:
    return sorted(_REGISTRY)


class EmptyParams(BaseModel):
    pass
