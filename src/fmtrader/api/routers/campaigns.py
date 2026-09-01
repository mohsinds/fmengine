"""Campaign control endpoints — FRONTEND_SPEC §7."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from fmtrader.agents.budget import BudgetCaps
from fmtrader.agents.campaign import CampaignConfig
from fmtrader.agents.journal import ResearchJournal
from fmtrader.agents.runner import (
    CampaignStore,
    create_campaign,
    signal_abort,
    signal_adjust_budget,
    signal_pause,
    signal_resume,
)
from fmtrader.api.deps import get_paths
from fmtrader.api.sse import SseEvent, throttled_sse
from fmtrader.core.errors import AgentError

router = APIRouter(tags=["campaigns"])


def _store() -> CampaignStore:
    return CampaignStore(get_paths().campaigns)


class CreateCampaignBody(BaseModel):
    name: str = "campaign"
    dataset_id: str
    strategy: str = "ema_cross"
    space_path: str = "configs/spaces/ema_cross.yaml"
    max_generations: int = 3
    proposals_per_generation: int = 5
    use_stub_llm: bool = True
    launch: bool = False


class BudgetPatch(BaseModel):
    per_campaign_usd: float | None = None
    per_day_usd: float | None = None
    per_generation_usd: float | None = None


@router.get("/campaigns")
def list_campaigns() -> dict[str, Any]:
    store = _store()
    items: list[dict[str, Any]] = []
    for cid in store.list_ids():
        try:
            state = store.load(cid)
        except AgentError:
            continue
        items.append(
            {
                "id": state.campaign_id,
                "status": state.status,
                "generation": state.generation,
                "strategy": state.config.strategy,
                "dataset_id": state.config.dataset_id,
                "name": state.config.name,
            }
        )
    return {"items": items, "count": len(items)}


@router.post("/campaigns")
def create_campaign_endpoint(body: CreateCampaignBody) -> dict[str, Any]:
    cfg = CampaignConfig(
        name=body.name,
        dataset_id=body.dataset_id,
        strategy=body.strategy,
        space_path=body.space_path,
        max_generations=body.max_generations,
        proposals_per_generation=body.proposals_per_generation,
        use_stub_llm=body.use_stub_llm,
    )
    state = create_campaign(cfg, store=_store())
    return {
        "id": state.campaign_id,
        "status": state.status,
        "launched": False,
        "message": "Created; launch via Temporal worker / CLI" if body.launch else "Created",
        "state": state.to_dict(),
    }


@router.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: str) -> dict[str, Any]:
    try:
        state = _store().load(campaign_id)
    except AgentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return state.to_dict()


@router.post("/campaigns/{campaign_id}/pause")
def pause_campaign(campaign_id: str) -> dict[str, Any]:
    try:
        state = signal_pause(campaign_id, store=_store())
    except AgentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return state.to_dict()


@router.post("/campaigns/{campaign_id}/resume")
def resume_campaign(campaign_id: str) -> dict[str, Any]:
    try:
        state = signal_resume(campaign_id, store=_store())
    except AgentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return state.to_dict()


@router.post("/campaigns/{campaign_id}/abort")
def abort_campaign(campaign_id: str) -> dict[str, Any]:
    try:
        state = signal_abort(campaign_id, store=_store())
    except AgentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return state.to_dict()


@router.patch("/campaigns/{campaign_id}/budget")
def patch_budget(campaign_id: str, body: BudgetPatch) -> dict[str, Any]:
    store = _store()
    try:
        state = store.load(campaign_id)
    except AgentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    base = state.budget_override or state.config.budget
    caps = BudgetCaps(
        per_campaign_usd=(
            body.per_campaign_usd if body.per_campaign_usd is not None else base.per_campaign_usd
        ),
        per_day_usd=body.per_day_usd if body.per_day_usd is not None else base.per_day_usd,
        per_generation_usd=(
            body.per_generation_usd
            if body.per_generation_usd is not None
            else base.per_generation_usd
        ),
    )
    state = signal_adjust_budget(campaign_id, caps, store=store)
    return {"id": campaign_id, "budget": caps.__dict__, "status": state.status}


@router.get("/campaigns/{campaign_id}/generations")
def list_generations(campaign_id: str) -> dict[str, Any]:
    try:
        state = _store().load(campaign_id)
    except AgentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    gens = [{"n": n, "status": "stub"} for n in range(1, state.generation + 1)]
    return {"campaign_id": campaign_id, "generations": gens, "current": state.generation}


@router.get("/campaigns/{campaign_id}/generations/{n}")
def get_generation(campaign_id: str, n: int) -> dict[str, Any]:
    try:
        state = _store().load(campaign_id)
    except AgentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if n < 1 or n > state.generation:
        raise HTTPException(status_code=404, detail=f"Generation {n} not found")
    return {
        "campaign_id": campaign_id,
        "generation": n,
        "survivors": state.survivors if n == state.generation else [],
        "search_space": state.search_space,
        "status": "stub",
    }


@router.get("/campaigns/{campaign_id}/journal")
def get_journal(campaign_id: str) -> dict[str, Any]:
    try:
        _store().load(campaign_id)
    except AgentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    md = ResearchJournal().read_report(campaign_id)
    return {"campaign_id": campaign_id, "markdown": md}


@router.get("/campaigns/{campaign_id}/stream")
async def campaign_stream(
    campaign_id: str,
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    store = _store()
    try:
        store.load(campaign_id)
    except AgentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    seq = 0

    def produce() -> list[SseEvent]:
        nonlocal seq
        state = store.load(campaign_id)
        seq += 1
        return [
            SseEvent(
                event="campaign.status",
                data={
                    "id": campaign_id,
                    "status": state.status,
                    "generation": state.generation,
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
