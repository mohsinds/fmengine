"""Feature / indicator registry endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

import fmtrader.features  # noqa: F401 — populate indicator registry
from fmtrader.core.errors import FeatureError
from fmtrader.features.registry import get_indicator, list_indicators

router = APIRouter(tags=["features"])


@router.get("/features")
def features_list(category: str | None = None) -> dict[str, Any]:
    specs = list_indicators(category=category)
    items = [
        {
            "name": s.name,
            "category": s.category,
            "requires": list(s.requires),
            "requires_volume": s.requires_volume,
            "requires_spread": s.requires_spread,
            "requires_open_interest": s.requires_open_interest,
            "multi_output": s.multi_output,
            "output_columns": list(s.output_columns) if s.output_columns else None,
        }
        for s in specs
    ]
    return {"items": items, "count": len(items)}


@router.get("/features/{name}/distribution")
def feature_distribution(
    name: str,
    dataset_id: str | None = Query(default=None),
) -> dict[str, Any]:
    try:
        get_indicator(name)
    except FeatureError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "name": name,
        "dataset_id": dataset_id,
        "histogram": [],
        "stats": {},
        "status": "stub",
    }
