"""System health, resources, settings, SSE."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse

from fmtrader.api.deps import get_paths
from fmtrader.api.sse import SseEvent, throttled_sse
from fmtrader.system.health import run_all_health_checks
from fmtrader.system.memory import collect_memory_snapshot

router = APIRouter(tags=["system"])


@router.get("/system/health")
def system_health() -> dict[str, Any]:
    results = run_all_health_checks()
    return {
        "ok": all(r.ok for r in results),
        "services": [
            {
                "name": r.name,
                "ok": r.ok,
                "latency_ms": r.latency_ms,
                "detail": r.detail,
            }
            for r in results
        ],
    }


@router.get("/system/resources")
def system_resources() -> dict[str, Any]:
    snap = collect_memory_snapshot()
    return {
        "total_gb": snap.total_gb,
        "used_gb": snap.used_gb,
        "available_gb": snap.available_gb,
        "docker_gb": snap.docker_gb,
        "ollama_gb": snap.ollama_gb,
        "python_workers_gb": snap.python_workers_gb,
        "within_budget": snap.within_budget,
        "budget": {
            "docker_gb": snap.budget_docker_gb,
            "ollama_gb": snap.budget_ollama_gb,
            "workers_gb": snap.budget_workers_gb,
            "headroom_gb": snap.budget_headroom_gb,
            "total_gb": snap.budget_total_gb,
        },
    }


@router.get("/settings")
def get_settings() -> dict[str, Any]:
    path = get_paths().settings_file
    if not path.exists():
        return {"theme": "dark", "equity_default_points": 2000}
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


@router.patch("/settings")
def patch_settings(body: dict[str, Any]) -> dict[str, Any]:
    path = get_paths().settings_file
    path.parent.mkdir(parents=True, exist_ok=True)
    current = get_settings()
    current.update(body)
    path.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    return current


@router.get("/system/stream")
async def system_stream(
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    seq = 0

    def produce() -> list[SseEvent]:
        nonlocal seq
        snap = collect_memory_snapshot()
        seq += 1
        return [
            SseEvent(
                event="resources",
                data={"within_budget": snap.within_budget, "used_gb": snap.used_gb},
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
