"""Holdout vault and kill-switch endpoints."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from fmtrader.api.deps import get_paths
from fmtrader.backtest.validation.holdout import HoldoutVault
from fmtrader.core.errors import HoldoutError
from fmtrader.risk.limits import KillSwitch
from fmtrader.strategy import library as _library  # noqa: F401
from fmtrader.strategy.base import list_strategies

router = APIRouter(tags=["vault"])


def _vault() -> HoldoutVault:
    return HoldoutVault(Path("data/holdout"))


def _kill() -> KillSwitch:
    return KillSwitch(path=get_paths().kill_switch)


def _append_audit(entry: dict[str, Any]) -> None:
    path = get_paths().vault_audit
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


@router.get("/vault/status")
def vault_status() -> dict[str, Any]:
    vault = _vault()
    strategies = list_strategies()
    per: list[dict[str, Any]] = []
    for name in strategies:
        per.append({"strategy": name, "consumed": vault.is_consumed(name), "locked": True})
    return {"strategies": per, "count": len(per)}


class UnlockBody(BaseModel):
    strategy: str
    dataset_id: str
    justification: str = Field(min_length=1)
    actor: str = "api"


@router.post("/vault/unlock")
def vault_unlock(body: UnlockBody) -> dict[str, Any]:
    vault = _vault()
    try:
        token = vault.issue_token(
            strategy=body.strategy,
            dataset_id=body.dataset_id,
            justification=body.justification,
        )
    except HoldoutError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    entry = {
        "at": datetime.now(tz=UTC).isoformat(),
        "event": "unlock_issued",
        "strategy": body.strategy,
        "dataset_id": body.dataset_id,
        "justification": body.justification,
        "token_id": token.token_id,
        "actor": body.actor,
    }
    _append_audit(entry)
    return {"token": token.to_dict(), "audit": entry}


@router.get("/vault/audit")
def vault_audit() -> dict[str, Any]:
    path = get_paths().vault_audit
    entries: list[dict[str, Any]] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return {"entries": entries, "count": len(entries)}


@router.get("/vault/kill-switch")
def kill_switch_get() -> dict[str, Any]:
    return _kill().status()


class EngageBody(BaseModel):
    reason: str = Field(min_length=1)
    engaged_by: str = "operator"


@router.post("/vault/kill-switch/engage")
def kill_switch_engage(body: EngageBody) -> dict[str, Any]:
    ks = _kill()
    ks.engage(reason=body.reason, engaged_by=body.engaged_by)
    return ks.status()


class ClearBody(BaseModel):
    cleared_by: str = "operator"


@router.post("/vault/kill-switch/clear")
def kill_switch_clear(body: ClearBody | None = None) -> dict[str, Any]:
    body = body or ClearBody()
    ks = _kill()
    ks.clear(cleared_by=body.cleared_by)
    return ks.status()
