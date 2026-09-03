"""Temporal activities wrapping campaign nodes.

Payloads are slim (campaign_id only). Full campaign state lives on disk via
``CampaignStore`` so Temporal workflow history does not grow with the leaderboard.
"""

from __future__ import annotations

from typing import Any

from fmtrader.agents.budget import BudgetCaps, BudgetGovernor
from fmtrader.agents.campaign import CampaignState
from fmtrader.agents.journal import ResearchJournal
from fmtrader.agents.ledger import CostLedger
from fmtrader.agents.llm import LLMRouter, StubLLMClient, default_router
from fmtrader.agents.runner import (
    CampaignStore,
    _stub_hypothesize_payload,
    finalize_campaign,
    run_generation,
)


def _router_for(state: CampaignState) -> LLMRouter:
    caps = state.budget_override or state.config.budget
    ledger = CostLedger()
    if state.config.use_stub_llm:
        gov = BudgetGovernor(caps, ledger=ledger)
        return LLMRouter(
            gov,
            local=StubLLMClient(response=_stub_hypothesize_payload(state)),
            frontier=StubLLMClient(response='{"critique":"stub"}'),
        )
    return default_router(
        caps=caps,
        ledger=ledger,
        stub=False,
        campaign_id=state.campaign_id,
        sweep_active=False,
        routing=state.config.llm_routing,
    )


def _apply_payload_overrides(state: CampaignState, payload: dict[str, Any]) -> None:
    bo = payload.get("budget_override")
    if isinstance(bo, dict):
        state.budget_override = BudgetCaps(
            per_campaign_usd=float(bo.get("per_campaign_usd", 0) or 0),
            per_day_usd=float(bo.get("per_day_usd", 0) or 0),
            per_generation_usd=float(bo.get("per_generation_usd", 0) or 0),
            openai_usd=float(bo.get("openai_usd", 0) or 0),
            anthropic_usd=float(bo.get("anthropic_usd", 0) or 0),
        )
    if "pause_requested" in payload:
        state.pause_requested = bool(payload["pause_requested"])
    if "abort_requested" in payload:
        state.abort_requested = bool(payload["abort_requested"])


def _slim(state: CampaignState) -> dict[str, Any]:
    """Activity/workflow result — never include leaderboard or search spaces."""
    return {
        "campaign_id": state.campaign_id,
        "generation": state.generation,
        "status": state.status,
        "max_generations": state.config.max_generations,
        "pause_requested": state.pause_requested,
        "abort_requested": state.abort_requested,
        "survivor_count": len(state.survivors),
        "leaderboard_count": len(state.leaderboard),
        "last_error": state.last_error,
        "initial_cash": state.config.initial_cash,
        "use_stub_llm": state.config.use_stub_llm,
    }


async def load_campaign_snapshot_activity(campaign_id: str) -> dict[str, Any]:
    state = CampaignStore().load(campaign_id)
    return _slim(state)


async def run_generation_activity(payload: dict[str, Any]) -> dict[str, Any]:
    campaign_id = str(payload["campaign_id"])
    store = CampaignStore()
    state = store.load(campaign_id)
    _apply_payload_overrides(state, payload)

    if state.pause_requested:
        state.status = "paused"
        store.save(state)
        return _slim(state)
    if state.abort_requested:
        state.status = "aborted"
        store.save(state)
        return _slim(state)

    try:
        from temporalio import activity

        activity.heartbeat(f"generation-{state.generation + 1}")
    except Exception:
        pass

    state = run_generation(state, router=_router_for(state), journal=ResearchJournal())
    store.save(state)
    return _slim(state)


async def checkpoint_activity(payload: dict[str, Any]) -> dict[str, Any]:
    """No-op slim checkpoint — state is already on disk after each generation."""
    campaign_id = str(payload["campaign_id"] if isinstance(payload, dict) else payload)
    return _slim(CampaignStore().load(campaign_id))


async def finalize_campaign_activity(payload: dict[str, Any]) -> dict[str, Any]:
    campaign_id = str(payload["campaign_id"] if isinstance(payload, dict) else payload)
    store = CampaignStore()
    state = store.load(campaign_id)
    if state.status not in {"aborted", "paused", "failed"}:
        state.status = "completed"
    state = finalize_campaign(state, journal=ResearchJournal(), store=store)
    return _slim(state)


def temporal_activity_defs() -> list[Any]:
    """Wrap plain coroutines with Temporal decorators when temporalio is installed."""
    try:
        from temporalio import activity
    except ImportError:
        return [
            load_campaign_snapshot_activity,
            run_generation_activity,
            checkpoint_activity,
            finalize_campaign_activity,
        ]
    return [
        activity.defn(name="load_campaign_snapshot_activity")(load_campaign_snapshot_activity),
        activity.defn(name="run_generation_activity")(run_generation_activity),
        activity.defn(name="checkpoint_activity")(checkpoint_activity),
        activity.defn(name="finalize_campaign_activity")(finalize_campaign_activity),
    ]


_ = BudgetCaps
