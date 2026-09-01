"""Trial registry explorer endpoints."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from fmtrader.api.deps import get_paths
from fmtrader.backtest.validation.dsr import deflated_sharpe, expected_max_sharpe
from fmtrader.backtest.validation.registry import TrialRegistry

router = APIRouter(tags=["registry"])


def _registry() -> TrialRegistry:
    return TrialRegistry(get_paths().registry)


def _row_to_item(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "strategy": row["strategy"],
        "params": json.loads(row["params_json"]),
        "config_hash": row["config_hash"],
        "metrics": json.loads(row["metrics_json"]),
        "source": row["source"],
        "dataset_id": row["dataset_id"],
        "lane": row["lane"],
        "execution_id": row["execution_id"],
        "created_at": row["created_at"],
    }


@router.get("/registry/trials")
def list_trials(
    strategy: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    reg = _registry()
    with reg._connect() as conn:
        if strategy is None:
            total = conn.execute("SELECT COUNT(*) AS n FROM trials").fetchone()["n"]
            rows = conn.execute(
                "SELECT * FROM trials ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        else:
            total = conn.execute(
                "SELECT COUNT(*) AS n FROM trials WHERE strategy = ?", (strategy,)
            ).fetchone()["n"]
            rows = conn.execute(
                "SELECT * FROM trials WHERE strategy = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                (strategy, limit, offset),
            ).fetchall()
    return {
        "items": [_row_to_item(r) for r in rows],
        "offset": offset,
        "limit": limit,
        "total": int(total),
    }


@router.get("/registry/counts")
def trial_counts() -> dict[str, Any]:
    reg = _registry()
    with reg._connect() as conn:
        rows = conn.execute(
            "SELECT strategy, COUNT(*) AS n FROM trials GROUP BY strategy ORDER BY strategy"
        ).fetchall()
    by_strategy = {str(r["strategy"]): int(r["n"]) for r in rows}
    return {"total": reg.count(), "by_strategy": by_strategy}


@router.get("/registry/surface")
def registry_surface(
    x: str = Query(...),
    y: str = Query(...),
    metric: str = Query(default="sharpe"),
    strategy: str | None = None,
) -> dict[str, Any]:
    return {
        "x": x,
        "y": y,
        "metric": metric,
        "strategy": strategy,
        "cells": [],
        "status": "stub",
    }


class DeflateBody(BaseModel):
    trial_ids: list[int] = Field(default_factory=list)
    n_returns: int = 100_000


@router.post("/registry/deflate")
def registry_deflate(body: DeflateBody) -> dict[str, Any]:
    if not body.trial_ids:
        raise HTTPException(status_code=400, detail="trial_ids required")
    reg = _registry()
    with reg._connect() as conn:
        placeholders = ",".join("?" for _ in body.trial_ids)
        rows = conn.execute(
            f"SELECT * FROM trials WHERE id IN ({placeholders})",
            body.trial_ids,
        ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="No trials found for given ids")

    results: list[dict[str, Any]] = []
    n_trials = reg.count()
    for r in rows:
        metrics = json.loads(r["metrics_json"])
        sharpe = float(metrics.get("sharpe") or metrics.get("sharpe_net") or 0.0)
        dsr = deflated_sharpe(sharpe, n_trials=max(n_trials, 1), n_returns=body.n_returns)
        pbo = min(1.0, 0.5 + 0.5 * (1.0 - dsr))
        results.append(
            {
                "id": int(r["id"]),
                "strategy": r["strategy"],
                "observed_sharpe": sharpe,
                "n_trials": n_trials,
                "expected_max_sharpe": expected_max_sharpe(n_trials=max(n_trials, 1)),
                "dsr": dsr,
                "pbo": pbo,
            }
        )
    return {"items": results, "n_trials": n_trials}
