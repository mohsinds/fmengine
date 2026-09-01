"""Generation loop nodes — hypothesize → validate → sweep → shortlist → … → journal."""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any

from fmtrader.agents.campaign import CampaignState, load_search_space
from fmtrader.agents.journal import ResearchJournal
from fmtrader.agents.llm import LLMRouter
from fmtrader.agents.proposals import (
    StrategyProposal,
    parse_proposals_from_llm_text,
    validate_proposal,
)
from fmtrader.backtest.runner import load_cost_config, run_backtest
from fmtrader.backtest.validation.dsr import deflated_sharpe
from fmtrader.backtest.validation.gates import evaluate_gates
from fmtrader.backtest.validation.registry import TrialRegistry, default_registry
from fmtrader.core.errors import AgentError
from fmtrader.system.logging import get_logger

log = get_logger(__name__)


def _sample_space(
    space: dict[str, list[Any]], *, n: int, seed: int, strategy: str
) -> list[dict[str, Any]]:
    keys = sorted(space.keys())
    if not keys:
        return [{"strategy": strategy, "params": {}, "rationale": "empty space"}]
    combos = list(itertools.product(*(space[k] for k in keys)))
    # Deterministic subsample
    step = max(1, len(combos) // max(n, 1))
    picked = combos[seed % max(1, step) :: step][:n]
    out: list[dict[str, Any]] = []
    for combo in picked:
        params = {k: v for k, v in zip(keys, combo, strict=True)}
        out.append(
            {
                "strategy": strategy,
                "params": params,
                "rationale": f"grid sample seed={seed}",
            }
        )
    return out


def hypothesize(state: CampaignState, router: LLMRouter) -> list[dict[str, Any]]:
    """Propose N candidate configs. Uses LLM when available; falls back to grid sample."""
    space = state.search_space or load_search_space(Path(state.config.space_path))
    state.search_space = space
    n = state.config.proposals_per_generation
    prompt = (
        f"Propose {n} JSON objects for strategy {state.config.strategy} "
        f"with params from space {json.dumps(space)}. "
        'Return a JSON array of {"strategy","params","rationale"}.'
    )
    try:
        result = router.complete(
            prompt,
            purpose="hypothesize",
            campaign_id=state.campaign_id,
            generation=state.generation,
        )
        parsed = parse_proposals_from_llm_text(str(result["text"]))
        if parsed:
            for p in parsed:
                p.setdefault("strategy", state.config.strategy)
            return parsed[:n]
    except Exception as exc:
        log.warning("hypothesize_llm_failed", error=str(exc))
    return _sample_space(
        space, n=n, seed=state.config.seed + state.generation, strategy=state.config.strategy
    )


def validate_proposals(
    raw: list[dict[str, Any]],
    state: CampaignState,
    *,
    registry: TrialRegistry | None = None,
) -> list[StrategyProposal]:
    registry = registry or default_registry()
    valid: list[StrategyProposal] = []
    for item in raw:
        try:
            prop = validate_proposal(
                item,
                search_space=state.search_space,
                registry=registry,
            )
            valid.append(prop)
        except AgentError as exc:
            log.info("proposal_rejected", reason=str(exc), proposal=item)
    return valid


def fast_sweep(
    proposals: list[StrategyProposal],
    state: CampaignState,
) -> list[dict[str, Any]]:
    """Evaluate proposals on the vectorbt triage lane."""
    cost = load_cost_config(Path(state.config.cost_config))
    results: list[dict[str, Any]] = []
    for prop in proposals:
        try:
            man = run_backtest(
                strategy=prop.strategy,
                params=prop.params,
                dataset_id=state.config.dataset_id,
                lane="vectorbt",
                cost_cfg=cost,
                cost_multiplier=1.0,
                seed=state.config.seed,
                run_sensitivity=False,
                max_bars=state.config.max_bars,
                source="agent",
            )
            metrics = man.metrics_net
            results.append(
                {
                    "strategy": prop.strategy,
                    "params": prop.params,
                    "execution_id": man.execution_id,
                    "sharpe": metrics.get("sharpe"),
                    "total_return_net": metrics.get("total_return_net"),
                    "trade_count": man.trade_count,
                    "cost_drag_pct": man.cost_drag_pct,
                    "lane": "vectorbt",
                }
            )
        except Exception as exc:
            log.warning("fast_sweep_failed", error=str(exc), params=prop.params)
            results.append(
                {
                    "strategy": prop.strategy,
                    "params": prop.params,
                    "error": str(exc),
                    "sharpe": None,
                    "lane": "vectorbt",
                }
            )
    return results


def shortlist(
    results: list[dict[str, Any]],
    state: CampaignState,
    *,
    registry: TrialRegistry | None = None,
) -> list[dict[str, Any]]:
    registry = registry or default_registry()
    n_trials = max(registry.count(strategy=state.config.strategy), 1)
    scored: list[dict[str, Any]] = []
    for r in results:
        if r.get("sharpe") is None or r.get("error"):
            continue
        sharpe = float(r["sharpe"])
        dsr = deflated_sharpe(
            sharpe, n_trials=n_trials, n_returns=max((state.config.max_bars or 5000) - 1, 2)
        )
        gate = evaluate_gates(
            dsr=dsr,
            pbo=0.4,  # unknown without CSCV matrix; conservative placeholder
            net_sharpe_1x=sharpe,
            net_sharpe_15x=sharpe,  # sensitivity skipped in fast path
            cost_drag_pct=float(r.get("cost_drag_pct") or 0.0),
            trade_count=int(r.get("trade_count") or 0),
            holdout_consumed=False,
        )
        item = {**r, "dsr": dsr, "verdict": gate.verdict}
        if gate.verdict not in {"NOISE"}:
            scored.append(item)
        else:
            log.info("shortlist_drop_noise", params=r.get("params"), dsr=dsr)
    scored.sort(key=lambda x: float(x.get("sharpe") or -999), reverse=True)
    # If everything is NOISE, still keep top-1 for journal honesty
    if not scored and results:
        ok = [r for r in results if r.get("sharpe") is not None]
        ok.sort(key=lambda x: float(x.get("sharpe") or -999), reverse=True)
        return [{**ok[0], "verdict": "NOISE", "dsr": 0.0}][:1] if ok else []
    return scored[: state.config.shortlist_size]


def fidelity_eval(shortlisted: list[dict[str, Any]], state: CampaignState) -> list[dict[str, Any]]:
    if not state.config.run_fidelity:
        return [{**r, "lane": r.get("lane", "vectorbt")} for r in shortlisted]
    cost = load_cost_config(Path(state.config.cost_config))
    out: list[dict[str, Any]] = []
    for r in shortlisted:
        try:
            man = run_backtest(
                strategy=str(r["strategy"]),
                params=dict(r["params"]),
                dataset_id=state.config.dataset_id,
                lane="nautilus",
                cost_cfg=cost,
                seed=state.config.seed,
                run_sensitivity=False,
                max_bars=state.config.max_bars,
                source="agent",
            )
            out.append(
                {
                    **r,
                    "lane": "nautilus",
                    "fidelity_execution_id": man.execution_id,
                    "sharpe": man.metrics_net.get("sharpe"),
                    "total_return_net": man.metrics_net.get("total_return_net"),
                }
            )
        except Exception as exc:
            out.append({**r, "fidelity_error": str(exc)})
    return out


def critique_and_select(
    state: CampaignState,
    router: LLMRouter,
    results: list[dict[str, Any]],
    shortlisted: list[dict[str, Any]],
) -> tuple[str, str, list[dict[str, Any]], dict[str, list[Any]]]:
    prompt = (
        f"Critique these shortlist results for campaign {state.campaign_id} gen {state.generation}: "
        f"{json.dumps(shortlisted)[:2000]}. Suggest next search space refinement as JSON."
    )
    critique = "(stub critique)"
    decision = "Keep top survivors; shrink search space around best params."
    try:
        out = router.complete(
            prompt,
            purpose="critique",
            campaign_id=state.campaign_id,
            generation=state.generation,
        )
        critique = str(out["text"])[:2000]
    except Exception as exc:
        critique = f"(critique unavailable: {exc})"

    survivors = shortlisted[: state.config.shortlist_size]
    # Shrink space around survivor params when possible
    next_space = dict(state.search_space)
    if survivors and state.search_space:
        best = survivors[0].get("params") or {}
        for k, v in best.items():
            if k in next_space and isinstance(next_space[k], list) and v in next_space[k]:
                vals = next_space[k]
                idx = vals.index(v)
                lo = max(0, idx - 1)
                hi = min(len(vals), idx + 2)
                next_space[k] = vals[lo:hi]
    decision = f"Survivors={len(survivors)}. " + decision
    return critique, decision, survivors, next_space


def write_journal(
    state: CampaignState,
    *,
    hypothesis: str,
    proposals: list[dict[str, Any]],
    results: list[dict[str, Any]],
    survivors: list[dict[str, Any]],
    next_search_space: dict[str, Any],
    critique: str,
    decision: str,
    journal: ResearchJournal | None = None,
) -> Path:
    journal = journal or ResearchJournal()
    path = journal.write_generation(
        campaign_id=state.campaign_id,
        generation=state.generation,
        hypothesis=hypothesis,
        proposals=proposals,
        results=results,
        survivors=survivors,
        next_search_space=next_search_space,
        critique=critique,
        decision=decision,
    )
    state.journal_paths.append(str(path))
    return path
