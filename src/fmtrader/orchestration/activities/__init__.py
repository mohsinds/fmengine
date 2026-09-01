"""Temporal activities wrapping campaign nodes."""

from __future__ import annotations

from typing import Any

from fmtrader.agents.budget import BudgetCaps, BudgetGovernor
from fmtrader.agents.campaign import CampaignState
from fmtrader.agents.journal import ResearchJournal
from fmtrader.agents.ledger import CostLedger
from fmtrader.agents.llm import LLMRouter, StubLLMClient
from fmtrader.agents.runner import CampaignStore, run_generation


def _router_for(state: CampaignState) -> LLMRouter:
    caps = state.budget_override or state.config.budget
    gov = BudgetGovernor(caps, ledger=CostLedger())
    return LLMRouter(gov, local=StubLLMClient(response="[]"), frontier=StubLLMClient())


async def run_generation_activity(state_dict: dict[str, Any]) -> dict[str, Any]:
    state = CampaignState.from_dict(state_dict)
    if state.pause_requested:
        state.status = "paused"
        CampaignStore().save(state)
        return state.to_dict()
    if state.abort_requested:
        state.status = "aborted"
        CampaignStore().save(state)
        return state.to_dict()
    try:
        from temporalio import activity

        activity.heartbeat(f"generation-{state.generation + 1}")
    except ImportError:
        pass
    state = run_generation(state, router=_router_for(state), journal=ResearchJournal())
    CampaignStore().save(state)
    return state.to_dict()


async def checkpoint_activity(state_dict: dict[str, Any]) -> dict[str, Any]:
    state = CampaignState.from_dict(state_dict)
    CampaignStore().save(state)
    return state.to_dict()


def temporal_activity_defs() -> list[Any]:
    """Wrap plain coroutines with Temporal decorators when temporalio is installed."""
    try:
        from temporalio import activity
    except ImportError:
        return [run_generation_activity, checkpoint_activity]
    return [
        activity.defn(name="run_generation_activity")(run_generation_activity),
        activity.defn(name="checkpoint_activity")(checkpoint_activity),
    ]


_ = BudgetCaps
