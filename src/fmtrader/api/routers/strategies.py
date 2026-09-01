"""Strategy registry endpoints."""

from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from fmtrader.core.errors import FeatureError
from fmtrader.strategy import library as _library  # noqa: F401 — register strategies
from fmtrader.strategy.base import EmptyParams, get_strategy, list_strategies

router = APIRouter(tags=["strategies"])


def _params_schema(name: str) -> type[BaseModel]:
    try:
        strat = get_strategy(name)
    except FeatureError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    schema = getattr(strat, "params_schema", None) or getattr(type(strat), "params_schema", None)
    if schema is None:
        return EmptyParams
    return cast(type[BaseModel], schema)


@router.get("/strategies")
def strategies_list() -> dict[str, Any]:
    names = list_strategies()
    items = []
    for name in names:
        cls = type(get_strategy(name))
        schema = cast(type[BaseModel], getattr(cls, "params_schema", EmptyParams))
        items.append({"name": name, "params_schema": schema.model_json_schema()})
    return {"items": items, "count": len(items)}


@router.get("/strategies/{name}/schema")
def strategy_schema(name: str) -> dict[str, Any]:
    schema = _params_schema(name)
    return {"name": name, "schema": schema.model_json_schema()}


@router.get("/strategies/{name}/search-space")
def strategy_search_space(name: str) -> dict[str, Any]:
    _params_schema(name)
    return {
        "name": name,
        "ranges": {},
        "choices": {},
        "dependencies": [],
        "status": "stub",
    }


class ValidateBody(BaseModel):
    params: dict[str, Any] = {}
    dataset_id: str | None = None


@router.post("/strategies/{name}/validate")
def strategy_validate(name: str, body: ValidateBody) -> dict[str, Any]:
    schema = _params_schema(name)
    try:
        validated = schema(**body.params).model_dump()
    except PydanticValidationError as exc:
        return {"ok": False, "errors": exc.errors(), "params": body.params}

    data_requirements: list[dict[str, Any]] = []
    # Built-in strategies are OHLC-only; declare volume requirement only when asked
    # via strategy naming convention (future volume strategies).
    requires_volume = "volume" in name.lower() or name.lower().endswith("_vol")
    if requires_volume:
        data_requirements.append(
            {
                "capability": "has_volume",
                "required": True,
                "reason": f"Strategy {name!r} requires volume",
            }
        )

    missing: list[str] = []
    if body.dataset_id and data_requirements:
        from fmtrader.api.deps import get_paths
        from fmtrader.data.ingest import load_manifest

        try:
            snap = load_manifest(get_paths().snapshots, body.dataset_id)
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "errors": [{"msg": str(exc)}],
                "params": validated,
                "data_requirements": data_requirements,
            }
        for req in data_requirements:
            if req["capability"] == "has_volume" and not snap.has_volume:
                missing.append("has_volume")

    return {
        "ok": len(missing) == 0,
        "params": validated,
        "data_requirements": data_requirements,
        "missing_capabilities": missing,
        "dataset_id": body.dataset_id,
    }
