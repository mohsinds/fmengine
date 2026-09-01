"""Execution review endpoints — FRONTEND_SPEC §18."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from fmtrader.api.deps import get_paths
from fmtrader.api.lttb import lttb
from fmtrader.api.promotion import audit_promotion, promotion_decision
from fmtrader.core.errors import FeatureError, ValidationError
from fmtrader.execution.recorder import ExecutionManifest, show_execution

router = APIRouter(tags=["executions"])


def _exec_root() -> Path:
    root = get_paths().executions
    root.mkdir(parents=True, exist_ok=True)
    return root


def load_manifest(execution_id: str) -> ExecutionManifest:
    try:
        return show_execution(_exec_root(), execution_id)
    except FeatureError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def list_execution_ids() -> list[str]:
    root = _exec_root()
    out: set[str] = set()
    for p in root.iterdir():
        if not p.is_file() or not p.name.endswith(".json"):
            continue
        name = p.name
        if name.endswith(".equity.json") or name.endswith(".trades.json"):
            continue
        if ".breakdown." in name:
            continue
        if name.endswith(".partial.json"):
            out.add(name[: -len(".partial.json")])
        else:
            out.add(p.stem)
    return sorted(out)


def _match_filters(
    man: ExecutionManifest,
    *,
    strategy: str | None,
    dataset: str | None,
    source: str | None,
    verdict: str | None,
) -> bool:
    if strategy and man.strategy != strategy:
        return False
    if dataset and man.dataset_id != dataset:
        return False
    if source:
        src = (man.metrics_net or {}).get("source") or (man.params or {}).get("source")
        if src != source:
            return False
    if verdict:
        v = (man.metrics_net or {}).get("verdict")
        if v != verdict:
            return False
    return True


def _load_json_sidecar(execution_id: str, suffix: str) -> Any | None:
    path = _exec_root() / f"{execution_id}{suffix}"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def equity_series(execution_id: str) -> tuple[list[float], list[float]]:
    raw = _load_json_sidecar(execution_id, ".equity.json")
    if isinstance(raw, dict) and "t" in raw and "equity" in raw:
        return [float(x) for x in raw["t"]], [float(y) for y in raw["equity"]]
    man = load_manifest(execution_id)
    ret = 0.0
    for key in ("total_return_net", "total_return", "return"):
        if key in man.metrics_net and man.metrics_net[key] is not None:
            try:
                ret = float(man.metrics_net[key])
                break
            except (TypeError, ValueError):
                continue
    n = max(int(man.trade_count or 0), 2)
    t = [float(i) for i in range(n)]
    equity = [1.0 + ret * (i / (n - 1)) for i in range(n)]
    return t, equity


def load_trades(execution_id: str) -> list[dict[str, Any]]:
    raw = _load_json_sidecar(execution_id, ".trades.json")
    if isinstance(raw, list):
        return [t for t in raw if isinstance(t, dict)]
    if isinstance(raw, dict) and isinstance(raw.get("trades"), list):
        return [t for t in raw["trades"] if isinstance(t, dict)]
    return []


class PromoteBody(BaseModel):
    override: bool = False
    justification: str | None = None
    min_dsr: float = 0.5
    max_pbo: float = 0.5
    actor: str = "api"


@router.get("/executions")
def list_executions(
    strategy: str | None = None,
    dataset: str | None = None,
    source: str | None = None,
    verdict: str | None = None,
    campaign: str | None = None,
    generation: int | None = None,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for eid in list_execution_ids():
        man = load_manifest(eid)
        if campaign is not None:
            c = (man.metrics_net or {}).get("campaign_id") or man.params.get("campaign_id")
            if c != campaign:
                continue
        if generation is not None:
            g = (man.metrics_net or {}).get("generation") or man.params.get("generation")
            if g != generation:
                continue
        if not _match_filters(
            man, strategy=strategy, dataset=dataset, source=source, verdict=verdict
        ):
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
                "trade_count": man.trade_count,
                "fragile": man.fragile,
                "started_at": man.started_at,
                "finished_at": man.finished_at,
            }
        )
    return {"items": items, "count": len(items)}


@router.get("/executions/{execution_id}")
def get_execution(execution_id: str) -> dict[str, Any]:
    man = load_manifest(execution_id)
    return {
        "id": man.execution_id,
        "summary": man.to_dict(),
        "verdict": (man.metrics_net or {}).get("verdict"),
        "gates": (man.metrics_net or {}).get("gates"),
    }


@router.get("/executions/{execution_id}/manifest")
def get_manifest(execution_id: str) -> dict[str, Any]:
    return load_manifest(execution_id).to_dict()


@router.get("/executions/{execution_id}/steps")
def get_steps(execution_id: str) -> dict[str, Any]:
    man = load_manifest(execution_id)
    return {"execution_id": execution_id, "steps": man.steps}


@router.get("/executions/{execution_id}/funnel")
def get_funnel(execution_id: str) -> dict[str, Any]:
    man = load_manifest(execution_id)
    return {"execution_id": execution_id, "funnel": man.funnel}


@router.get("/executions/{execution_id}/performance")
def get_performance(execution_id: str) -> dict[str, Any]:
    man = load_manifest(execution_id)
    return {
        "execution_id": execution_id,
        "metrics_gross": man.metrics_gross,
        "metrics_net": man.metrics_net,
        "cost_drag_pct": man.cost_drag_pct,
        "cost_sensitivity": man.cost_sensitivity,
        "trade_count": man.trade_count,
    }


@router.get("/executions/{execution_id}/breakdown")
def get_breakdown(
    execution_id: str,
    by: str = Query(default="session", pattern="^(session|hour|dow|regime|exit_reason|side|size)$"),
) -> dict[str, Any]:
    load_manifest(execution_id)
    raw = _load_json_sidecar(execution_id, f".breakdown.{by}.json")
    if isinstance(raw, dict):
        return raw
    return {"execution_id": execution_id, "dimension": by, "buckets": []}


@router.get("/executions/{execution_id}/trades")
def get_trades(
    execution_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    load_manifest(execution_id)
    trades = load_trades(execution_id)
    page = trades[offset : offset + limit]
    return {
        "execution_id": execution_id,
        "items": page,
        "offset": offset,
        "limit": limit,
        "total": len(trades),
    }


@router.get("/executions/{execution_id}/equity")
def get_equity(
    execution_id: str,
    points: int = Query(default=2000, ge=2, le=50_000),
) -> dict[str, Any]:
    load_manifest(execution_id)
    xs, ys = equity_series(execution_id)
    dx, dy = lttb(xs, ys, points)
    return {"execution_id": execution_id, "t": dx, "equity": dy, "points": len(dy)}


@router.get("/executions/{execution_id}/export")
def export_execution(execution_id: str) -> dict[str, Any]:
    man = load_manifest(execution_id)
    xs, ys = equity_series(execution_id)
    return {
        "manifest": man.to_dict(),
        "trades": load_trades(execution_id),
        "equity": {"t": xs, "equity": ys},
    }


@router.post("/executions/{execution_id}/promote")
def promote_execution(execution_id: str, body: PromoteBody | None = None) -> dict[str, Any]:
    body = body or PromoteBody()
    man = load_manifest(execution_id)
    try:
        decision = promotion_decision(
            man,
            min_dsr=body.min_dsr,
            max_pbo=body.max_pbo,
            override=body.override,
            justification=body.justification,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit_promotion(
        audit_path=get_paths().promotion_audit,
        execution_id=execution_id,
        decision=decision,
        actor=body.actor,
    )
    if not decision.allowed:
        raise HTTPException(
            status_code=409,
            detail={
                "allowed": False,
                "reason": decision.reason,
                "dsr": decision.dsr,
                "verdict": decision.verdict,
            },
        )
    return {
        "allowed": True,
        "reason": decision.reason,
        "dsr": decision.dsr,
        "verdict": decision.verdict,
        "override": decision.override,
    }
