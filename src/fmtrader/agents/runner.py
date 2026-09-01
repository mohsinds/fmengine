"""In-process campaign runner (durable Temporal wrapper calls the same nodes)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from fmtrader.agents.budget import BudgetCaps, BudgetGovernor
from fmtrader.agents.campaign import (
    CampaignConfig,
    CampaignState,
    bind_search_spaces,
    load_search_spaces,
)
from fmtrader.agents.journal import ResearchJournal
from fmtrader.agents.ledger import CostLedger
from fmtrader.agents.llm import LLMRouter, StubLLMClient, default_router
from fmtrader.agents.nodes import (
    build_leaderboard_summary,
    critique_and_select,
    fast_sweep,
    fidelity_eval,
    hypothesize,
    score_results,
    shortlist,
    validate_proposals,
    write_journal,
)
from fmtrader.core.errors import AgentError
from fmtrader.system.logging import get_logger

log = get_logger(__name__)


class CampaignStore:
    """Filesystem campaign state store."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path("data/campaigns")
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, campaign_id: str) -> Path:
        return self.root / f"{campaign_id}.json"

    def save(self, state: CampaignState) -> None:
        self.path(state.campaign_id).write_text(
            json.dumps(state.to_dict(), indent=2, default=str), encoding="utf-8"
        )

    def load(self, campaign_id: str) -> CampaignState:
        p = self.path(campaign_id)
        if not p.exists():
            raise AgentError(f"Campaign not found: {campaign_id}")
        return CampaignState.from_dict(json.loads(p.read_text(encoding="utf-8")))

    def list_ids(self) -> list[str]:
        return sorted(p.stem for p in self.root.glob("*.json"))


def new_campaign_id() -> str:
    return uuid.uuid4().hex


def create_campaign(config: CampaignConfig, *, store: CampaignStore | None = None) -> CampaignState:
    store = store or CampaignStore()
    raw = load_search_spaces(Path(config.space_path))
    spaces = bind_search_spaces(raw, list(config.strategies))
    state = CampaignState(
        campaign_id=new_campaign_id(),
        config=config,
        status="created",
        generation=0,
        search_spaces=spaces,
        search_space=spaces.get(config.strategy) or next(iter(spaces.values()), {}),
    )
    store.save(state)
    return state


def _stub_hypothesize_payload(state: CampaignState) -> str:
    """Stub hypothesize response.

    Empty array forces grid sampling across ``search_spaces`` (better for long soaks).
    When refining a tiny space, still emit one seed proposal per strategy.
    """
    if not state.config.refine_space:
        return "[]"
    spaces = state.search_spaces or {}
    props = []
    for name in state.config.strategies:
        space = spaces.get(name) or state.search_space
        props.append(
            {
                "strategy": name,
                "params": {k: (v[0] if v else None) for k, v in space.items()},
                "rationale": "stub",
            }
        )
    return json.dumps(props[: state.config.proposals_per_generation] or props)


def run_generation(
    state: CampaignState,
    *,
    router: LLMRouter,
    journal: ResearchJournal | None = None,
) -> CampaignState:
    """Execute one generation of the research loop (checkpointable unit)."""
    if state.abort_requested:
        state.status = "aborted"
        return state
    if state.pause_requested:
        state.status = "paused"
        return state

    state.status = "running"
    state.generation += 1
    hypothesis = (
        f"Generation {state.generation}: explore strategies {state.config.strategies} "
        f"spaces={list(state.search_spaces)}"
    )
    raw = hypothesize(state, router)
    valid = validate_proposals(raw, state)
    if not valid:
        # Registry dedupe emptied the batch — resample from grids with a shifted seed
        from fmtrader.agents.nodes import _sample_multi, ensure_spaces
        from fmtrader.agents.proposals import StrategyProposal

        spaces = ensure_spaces(state)
        resampled = _sample_multi(
            spaces,
            strategies=list(state.config.strategies),
            n=state.config.proposals_per_generation,
            seed=state.config.seed + state.generation * 97 + 13,
        )
        valid = validate_proposals(resampled, state)
        if not valid:
            valid = [
                StrategyProposal.model_validate(x)
                for x in resampled[: state.config.proposals_per_generation]
            ]
    results = fast_sweep(valid, state)
    scored = score_results(results, state)
    state.leaderboard.extend(scored)
    listed = shortlist(scored, state)
    fidelity = fidelity_eval(listed, state)
    critique, decision, survivors, next_spaces = critique_and_select(
        state, router, scored, fidelity
    )
    write_journal(
        state,
        hypothesis=hypothesis,
        proposals=[p.model_dump() for p in valid],
        results=scored,
        survivors=survivors,
        next_search_space=next_spaces,
        critique=critique,
        decision=decision,
        journal=journal,
    )
    state.survivors = survivors
    state.search_spaces = next_spaces
    state.search_space = next_spaces.get(state.config.strategy) or next(
        iter(next_spaces.values()), {}
    )
    return state


def run_campaign_local(
    state: CampaignState,
    *,
    store: CampaignStore | None = None,
    router: LLMRouter | None = None,
    journal: ResearchJournal | None = None,
    max_generations: int | None = None,
) -> CampaignState:
    """Run generations until complete / pause / abort (no Temporal required)."""
    store = store or CampaignStore()
    journal = journal or ResearchJournal()
    caps = state.budget_override or state.config.budget
    if router is None:
        ledger = CostLedger()
        gov = BudgetGovernor(caps, ledger=ledger)
        if state.config.use_stub_llm:
            router = LLMRouter(
                gov,
                local=StubLLMClient(response=_stub_hypothesize_payload(state)),
                frontier=StubLLMClient(response='{"critique":"stub"}'),
            )
        else:
            router = default_router(
                caps=caps,
                ledger=ledger,
                stub=False,
                campaign_id=state.campaign_id,
                sweep_active=True,
            )

    limit = max_generations if max_generations is not None else state.config.max_generations
    state.status = "running"
    store.save(state)

    while state.generation < limit:
        if state.abort_requested:
            state.status = "aborted"
            store.save(state)
            return state
        if state.pause_requested:
            state.status = "paused"
            store.save(state)
            return state
        try:
            state = run_generation(state, router=router, journal=journal)
            store.save(state)
        except Exception as exc:
            state.last_error = str(exc)
            state.status = "failed"
            store.save(state)
            log.error("campaign_failed", error=str(exc), campaign_id=state.campaign_id)
            raise

    state.status = "completed"
    state = finalize_campaign(state, journal=journal, store=store)
    return state


def finalize_campaign(
    state: CampaignState,
    *,
    journal: ResearchJournal | None = None,
    store: CampaignStore | None = None,
) -> CampaignState:
    """Write end-of-campaign leaderboard summary (local + Temporal)."""
    journal = journal or ResearchJournal()
    store = store or CampaignStore()
    if state.status == "completed":
        summary = build_leaderboard_summary(state)
        path = journal.write_summary(state.campaign_id, summary)
        state.journal_paths.append(str(path))
    store.save(state)
    return state


def signal_pause(campaign_id: str, *, store: CampaignStore | None = None) -> CampaignState:
    store = store or CampaignStore()
    state = store.load(campaign_id)
    state.pause_requested = True
    if state.status == "running":
        state.status = "paused"
    store.save(state)
    return state


def signal_resume(campaign_id: str, *, store: CampaignStore | None = None) -> CampaignState:
    store = store or CampaignStore()
    state = store.load(campaign_id)
    state.pause_requested = False
    if state.status == "paused":
        return run_campaign_local(state, store=store)
    store.save(state)
    return state


def signal_abort(campaign_id: str, *, store: CampaignStore | None = None) -> CampaignState:
    store = store or CampaignStore()
    state = store.load(campaign_id)
    state.abort_requested = True
    state.status = "aborted"
    store.save(state)
    return state


def signal_adjust_budget(
    campaign_id: str,
    caps: BudgetCaps,
    *,
    store: CampaignStore | None = None,
) -> CampaignState:
    store = store or CampaignStore()
    state = store.load(campaign_id)
    state.budget_override = caps
    store.save(state)
    return state
