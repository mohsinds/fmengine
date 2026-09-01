"""Optional LangGraph wiring — falls back to sequential nodes if langgraph absent."""

from __future__ import annotations

from typing import Any, TypedDict

from fmtrader.agents.campaign import CampaignState
from fmtrader.agents.llm import LLMRouter
from fmtrader.agents.runner import run_generation
from fmtrader.system.logging import get_logger

log = get_logger(__name__)


class GraphState(TypedDict, total=False):
    campaign: dict[str, Any]
    generation_done: bool


def build_research_graph(router: LLMRouter) -> Any:
    """Return a LangGraph compiled graph when available, else a simple callable."""
    try:
        from langgraph.graph import END, StateGraph
    except ImportError:
        log.info("langgraph_unavailable_using_sequential")

        def _run(state: CampaignState) -> CampaignState:
            return run_generation(state, router=router)

        return _run

    def _node(gstate: GraphState) -> GraphState:
        st = CampaignState.from_dict(gstate["campaign"])
        st = run_generation(st, router=router)
        return {"campaign": st.to_dict(), "generation_done": True}

    g = StateGraph(GraphState)
    g.add_node("generation", _node)
    g.set_entry_point("generation")
    g.add_edge("generation", END)
    return g.compile()
