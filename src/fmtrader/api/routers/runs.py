"""Runs API — alias of executions for FRONTEND_SPEC §7 /runs paths."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from fmtrader.api.deps import get_paths
from fmtrader.api.lttb import lttb
from fmtrader.api.routers.executions import (
    equity_series,
    list_execution_ids,
    load_manifest,
    load_trades,
)
from fmtrader.api.sse import SseEvent, throttled_sse
from fmtrader.backtest.runner import load_cost_config, run_backtest
from fmtrader.core.errors import FeatureError
from fmtrader.strategy import library as _library  # noqa: F401
from fmtrader.strategy.base import get_strategy

router = APIRouter(tags=["runs"])


class CreateRunBody(BaseModel):
    strategy: str
    dataset_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    lane: str = "vectorbt"
    max_bars: int | None = 5000
    cost_config: str = "configs/costs/xauusd_cfd.yaml"
    run_sensitivity: bool = True


class CompareBody(BaseModel):
    run_ids: list[str] = Field(min_length=2)


@router.get("/runs")
def list_runs(
    strategy: str | None = None,
    dataset: str | None = None,
    source: str | None = None,
    verdict: str | None = None,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for eid in list_execution_ids():
        man = load_manifest(eid)
        if strategy and man.strategy != strategy:
            continue
        if dataset and man.dataset_id != dataset:
            continue
        if source:
            src = (man.metrics_net or {}).get("source")
            if src != source:
                continue
        if verdict:
            v = (man.metrics_net or {}).get("verdict")
            if v != verdict:
                continue
        items.append(
            {
                "id": man.execution_id,
                "strategy": man.strategy,
                "dataset_id": man.dataset_id,
                "lane": man.lane,
                "status": man.status,
                "verdict": (man.metrics_net or {}).get("verdict"),
                "metrics_net": man.metrics_net,
                "started_at": man.started_at,
                "finished_at": man.finished_at,
            }
        )
    return {"items": items, "count": len(items)}


@router.post("/runs")
def create_run(body: CreateRunBody) -> dict[str, Any]:
    """Launch a manual Lab run — records trial with source=manual."""
    try:
        strat = get_strategy(body.strategy)
    except FeatureError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    schema = getattr(strat, "params_schema", None) or getattr(type(strat), "params_schema", None)
    if schema is not None:
        try:
            params = schema(**body.params).model_dump()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"Invalid params: {exc}") from exc
    else:
        params = dict(body.params)

    paths = get_paths()
    cost_path = Path(body.cost_config)
    if not cost_path.is_file():
        raise HTTPException(status_code=400, detail=f"Cost config not found: {cost_path}")
    cost_cfg = load_cost_config(cost_path)

    catalog = Path("data/catalog")
    snapshots = paths.snapshots if paths.snapshots.exists() else Path("data/snapshots")

    try:
        man = run_backtest(
            strategy=body.strategy,
            params=params,
            dataset_id=body.dataset_id,
            lane=body.lane,
            cost_cfg=cost_cfg,
            catalog_root=catalog,
            snapshots_dir=snapshots,
            executions_root=paths.executions,
            max_bars=body.max_bars,
            run_sensitivity=body.run_sensitivity,
            source="manual",
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    net = dict(man.metrics_net or {})
    net["source"] = "manual"
    man.metrics_net = net
    out_path = paths.executions / f"{man.execution_id}.json"
    if out_path.exists():
        data = json.loads(out_path.read_text(encoding="utf-8"))
        data["metrics_net"] = net
        out_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    return {
        "status": "complete",
        "id": man.execution_id,
        "execution_id": man.execution_id,
        "strategy": man.strategy,
        "params": man.params,
        "dataset_id": man.dataset_id,
        "lane": man.lane,
        "metrics_net": man.metrics_net,
        "metrics_gross": man.metrics_gross,
        "cost_drag_pct": man.cost_drag_pct,
        "trade_count": man.trade_count,
        "fragile": man.fragile,
        "cost_sensitivity": man.cost_sensitivity,
    }


@router.post("/runs/compare")
def compare_runs(body: CompareBody) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for rid in body.run_ids:
        man = load_manifest(rid)
        rows.append(
            {
                "id": man.execution_id,
                "strategy": man.strategy,
                "dataset_id": man.dataset_id,
                "metrics_net": man.metrics_net,
                "metrics_gross": man.metrics_gross,
                "trade_count": man.trade_count,
                "cost_drag_pct": man.cost_drag_pct,
                "verdict": (man.metrics_net or {}).get("verdict"),
            }
        )
    return {"runs": rows}


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    man = load_manifest(run_id)
    return {
        "id": man.execution_id,
        "summary": man.to_dict(),
        "verdict": (man.metrics_net or {}).get("verdict"),
        "gates": (man.metrics_net or {}).get("gates"),
    }


@router.get("/runs/{run_id}/equity")
def get_run_equity(
    run_id: str,
    points: int = Query(default=2000, ge=2, le=50_000),
) -> dict[str, Any]:
    load_manifest(run_id)
    xs, ys = equity_series(run_id)
    dx, dy = lttb(xs, ys, points)
    return {"id": run_id, "t": dx, "equity": dy, "points": len(dy)}


@router.get("/runs/{run_id}/trades")
def get_run_trades(
    run_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    load_manifest(run_id)
    trades = load_trades(run_id)
    return {
        "id": run_id,
        "items": trades[offset : offset + limit],
        "offset": offset,
        "limit": limit,
        "total": len(trades),
    }


@router.get("/runs/{run_id}/robustness")
def get_run_robustness(run_id: str) -> dict[str, Any]:
    load_manifest(run_id)
    return {
        "id": run_id,
        "top_trade_removal": None,
        "session_split": None,
        "neighborhood": None,
        "status": "stub",
    }


@router.get("/runs/{run_id}/stream")
async def run_stream(
    run_id: str,
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    man = load_manifest(run_id)
    seq = 0

    def produce() -> list[SseEvent]:
        nonlocal seq
        seq += 1
        progress = 100.0 if man.status == "complete" else (50.0 if man.status == "running" else 0.0)
        return [
            SseEvent(
                event="progress",
                data={
                    "id": run_id,
                    "status": man.status,
                    "progress": progress,
                    "metrics_net": man.metrics_net,
                },
                id=str(seq),
            )
        ]

    async def gen() -> Any:
        async for chunk in throttled_sse(
            produce, last_event_id=last_event_id, max_iterations=3, idle_sleep=0.05
        ):
            if await request.is_disconnected():
                break
            yield chunk

    return StreamingResponse(gen(), media_type="text/event-stream")
