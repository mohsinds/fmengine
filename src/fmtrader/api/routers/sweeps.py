"""Sweep preview and launch stubs."""

from __future__ import annotations

import math
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(tags=["sweeps"])


class SweepPreviewBody(BaseModel):
    strategy: str
    ranges: dict[str, list[Any]] = Field(default_factory=dict)
    dataset_id: str | None = None


class SweepLaunchBody(BaseModel):
    strategy: str
    ranges: dict[str, list[Any]] = Field(default_factory=dict)
    dataset_id: str
    lane: str = "vectorbt"


def _config_count(ranges: dict[str, list[Any]]) -> int:
    if not ranges:
        return 0
    n = 1
    for values in ranges.values():
        n *= max(len(values), 0)
        if n == 0:
            return 0
    return int(n)


@router.post("/sweeps/preview")
def sweeps_preview(body: SweepPreviewBody) -> dict[str, Any]:
    count = _config_count(body.ranges)
    warn = count >= 100
    return {
        "strategy": body.strategy,
        "config_count": count,
        "deflation_warning": warn,
        "message": (
            f"Large search space ({count} configs) will heavily deflate Sharpe" if warn else None
        ),
        "log10_trials": math.log10(count) if count > 0 else None,
    }


@router.post("/sweeps")
def sweeps_launch(body: SweepLaunchBody) -> dict[str, Any]:
    count = _config_count(body.ranges)
    return {
        "status": "stub",
        "message": "Sweep launch not wired; use fmtrader backtest sweep CLI",
        "strategy": body.strategy,
        "dataset_id": body.dataset_id,
        "config_count": count,
        "lane": body.lane,
    }
