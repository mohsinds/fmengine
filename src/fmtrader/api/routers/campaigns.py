"""Campaign control endpoints — FRONTEND_SPEC §7 + trace / ledger."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from fmtrader.agents.budget import BudgetCaps
from fmtrader.agents.campaign import CampaignConfig
from fmtrader.agents.ingredients import list_ingredients
from fmtrader.agents.journal import ResearchJournal
from fmtrader.agents.ledger import CostLedger
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
from fmtrader.orchestration.temporal_signals import signal_temporal_sync

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
                "max_generations": state.config.max_generations,
                "strategy": state.config.strategy,
                "dataset_id": state.config.dataset_id,
                "name": state.config.name,
                "use_stub_llm": state.config.use_stub_llm,
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
    out = state.to_dict()
    out["budget"] = {
        "per_campaign_usd": (state.budget_override or state.config.budget).per_campaign_usd,
        "per_day_usd": (state.budget_override or state.config.budget).per_day_usd,
        "per_generation_usd": (state.budget_override or state.config.budget).per_generation_usd,
        "openai_usd": (state.budget_override or state.config.budget).openai_usd,
        "anthropic_usd": (state.budget_override or state.config.budget).anthropic_usd,
        "spent_usd": CostLedger().spent_campaign(campaign_id),
    }
    return out


@router.post("/campaigns/{campaign_id}/pause")
def pause_campaign(campaign_id: str) -> dict[str, Any]:
    try:
        state = signal_pause(campaign_id, store=_store())
    except AgentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    temporal = signal_temporal_sync(campaign_id, "pause")
    out = state.to_dict()
    out["temporal_signaled"] = temporal
    return out


@router.post("/campaigns/{campaign_id}/resume")
def resume_campaign(campaign_id: str) -> dict[str, Any]:
    try:
        # Filesystem flag first; Temporal resume if workflow running
        store = _store()
        state = store.load(campaign_id)
        state.pause_requested = False
        if state.status == "paused":
            state.status = "running"
        store.save(state)
    except AgentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    temporal = signal_temporal_sync(campaign_id, "resume")
    if not temporal and state.status == "paused":
        # Local-only resume path
        state = signal_resume(campaign_id, store=_store())
    out = state.to_dict()
    out["temporal_signaled"] = temporal
    return out


@router.post("/campaigns/{campaign_id}/abort")
def abort_campaign(campaign_id: str) -> dict[str, Any]:
    try:
        state = signal_abort(campaign_id, store=_store())
    except AgentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    temporal = signal_temporal_sync(campaign_id, "abort")
    out = state.to_dict()
    out["temporal_signaled"] = temporal
    return out


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
        openai_usd=base.openai_usd,
        anthropic_usd=base.anthropic_usd,
    )
    state = signal_adjust_budget(campaign_id, caps, store=store)
    signal_temporal_sync(
        campaign_id,
        "adjust_budget",
        caps.per_campaign_usd,
        caps.per_day_usd,
        caps.per_generation_usd,
    )
    return {"id": campaign_id, "budget": caps.__dict__, "status": state.status}


@router.get("/campaigns/{campaign_id}/generations")
def list_generations(campaign_id: str) -> dict[str, Any]:
    try:
        state = _store().load(campaign_id)
    except AgentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    journal = ResearchJournal()
    gens = []
    for n in range(1, state.generation + 1):
        ev = next((e for e in state.decision_trace if int(e.get("generation", -1)) == n), None)
        if ev is None:
            for te in journal.read_trace(campaign_id):
                if int(te.get("generation", -1)) == n:
                    ev = te
                    break
        gens.append(
            {
                "n": n,
                "status": "complete" if n < state.generation or state.status != "running" else "current",
                "has_journal": journal.read_generation_markdown(campaign_id, n) is not None,
                "survivor_count": len(ev.get("survivors") or []) if ev else 0,
                "ingredients": (ev or {}).get("ingredients", {}).get("ingredients", []),
            }
        )
    return {"campaign_id": campaign_id, "generations": gens, "current": state.generation}


@router.get("/campaigns/{campaign_id}/generations/{n}")
def get_generation(campaign_id: str, n: int) -> dict[str, Any]:
    try:
        state = _store().load(campaign_id)
    except AgentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if n < 1 or n > max(state.generation, 0):
        raise HTTPException(status_code=404, detail=f"Generation {n} not found")
    journal = ResearchJournal()
    ev = next((e for e in state.decision_trace if int(e.get("generation", -1)) == n), None)
    if ev is None:
        for te in journal.read_trace(campaign_id):
            if int(te.get("generation", -1)) == n:
                ev = te
                break
    md = journal.read_generation_markdown(campaign_id, n)
    return {
        "campaign_id": campaign_id,
        "generation": n,
        "event": ev,
        "markdown": md,
        "survivors": (ev or {}).get("survivors")
        or (state.survivors if n == state.generation else []),
        "search_space": state.search_space if n == state.generation else None,
        "status": "ok",
    }


@router.get("/campaigns/{campaign_id}/journal")
def get_journal(campaign_id: str) -> dict[str, Any]:
    try:
        _store().load(campaign_id)
    except AgentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    md = ResearchJournal().read_report(campaign_id)
    return {"campaign_id": campaign_id, "markdown": md}


@router.get("/campaigns/{campaign_id}/trace")
def get_trace(campaign_id: str) -> dict[str, Any]:
    try:
        state = _store().load(campaign_id)
    except AgentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    disk = ResearchJournal().read_trace(campaign_id)
    # Prefer in-memory/state then merge disk
    by_gen: dict[int, dict[str, Any]] = {}
    for e in disk + list(state.decision_trace):
        g = int(e.get("generation", -1))
        if g >= 0:
            by_gen[g] = e
    events = [by_gen[k] for k in sorted(by_gen)]
    return {
        "campaign_id": campaign_id,
        "events": events,
        "count": len(events),
        "active_ingredients": state.active_ingredients,
    }


@router.get("/campaigns/{campaign_id}/llm-ledger")
def get_llm_ledger(campaign_id: str, limit: int = 200) -> dict[str, Any]:
    try:
        _store().load(campaign_id)
    except AgentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    ledger = CostLedger()
    return {
        "campaign_id": campaign_id,
        "spent_usd": ledger.spent_campaign(campaign_id),
        "entries": ledger.list_entries(campaign_id, limit=limit),
        "count": ledger.count(campaign_id=campaign_id),
    }


@router.get("/ingredients")
def get_ingredients() -> dict[str, Any]:
    items = list_ingredients()
    return {"items": items, "count": len(items)}


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
    last_gen = -1

    def produce() -> list[SseEvent]:
        nonlocal seq, last_gen
        state = store.load(campaign_id)
        seq += 1
        events = [
            SseEvent(
                event="campaign.status",
                data={
                    "id": campaign_id,
                    "status": state.status,
                    "generation": state.generation,
                    "max_generations": state.config.max_generations,
                    "spent_usd": CostLedger().spent_campaign(campaign_id),
                    "ingredients": state.active_ingredients,
                },
                id=str(seq),
            )
        ]
        if state.generation != last_gen:
            seq += 1
            events.append(
                SseEvent(
                    event="generation.progress",
                    data={
                        "id": campaign_id,
                        "generation": state.generation,
                        "status": state.status,
                    },
                    id=str(seq),
                )
            )
            last_gen = state.generation
        return events

    async def gen() -> Any:
        async for chunk in throttled_sse(
            produce, last_event_id=last_event_id, max_iterations=30, idle_sleep=0.5
        ):
            if await request.is_disconnected():
                break
            yield chunk

    return StreamingResponse(gen(), media_type="text/event-stream")
