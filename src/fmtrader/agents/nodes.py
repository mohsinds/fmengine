"""Generation loop nodes — hypothesize → validate → sweep → shortlist → … → journal."""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any

from fmtrader.agents.campaign import CampaignState, bind_search_spaces, load_search_spaces
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


def ensure_spaces(state: CampaignState) -> dict[str, dict[str, list[Any]]]:
    if state.search_spaces:
        return state.search_spaces
    raw = load_search_spaces(Path(state.config.space_path))
    spaces = bind_search_spaces(raw, list(state.config.strategies))
    state.search_spaces = spaces
    state.search_space = spaces.get(state.config.strategy) or next(iter(spaces.values()), {})
    return spaces


def _sample_space(
    space: dict[str, list[Any]], *, n: int, seed: int, strategy: str
) -> list[dict[str, Any]]:
    keys = sorted(space.keys())
    if not keys:
        return [{"strategy": strategy, "params": {}, "rationale": "empty space"}]
    combos = list(itertools.product(*(space[k] for k in keys)))
    # Prefer configs not already in the trial registry (exhaustive long soaks)
    try:
        from fmtrader.backtest.validation.registry import config_hash, default_registry

        reg = default_registry()
        fresh: list[tuple[Any, ...]] = []
        seen: list[tuple[Any, ...]] = []
        for combo in combos:
            params = {k: v for k, v in zip(keys, combo, strict=True)}
            if reg.has_config(config_hash(strategy, params)):
                seen.append(combo)
            else:
                fresh.append(combo)
        ordered = fresh if fresh else seen
    except Exception:
        ordered = combos
    step = max(1, len(ordered) // max(n, 1))
    picked = ordered[seed % max(1, step) :: step][:n]
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


def _sample_multi(
    spaces: dict[str, dict[str, list[Any]]],
    *,
    strategies: list[str],
    n: int,
    seed: int,
) -> list[dict[str, Any]]:
    """Round-robin grid samples across strategies."""
    if not strategies:
        return []
    base = max(1, n // len(strategies))
    rem = n - base * len(strategies)
    out: list[dict[str, Any]] = []
    for i, name in enumerate(strategies):
        take = base + (1 if i < rem else 0)
        space = spaces.get(name) or {}
        out.extend(_sample_space(space, n=take, seed=seed + i * 17, strategy=name))
    return out[:n]


def _agent_memory_block(state: CampaignState) -> str:
    if not state.config.use_agent_memory:
        return ""
    from fmtrader.agents.memory import build_agent_memory

    try:
        return build_agent_memory(
            dataset_id=state.config.dataset_id,
            strategies=list(state.config.strategies),
            decision_trace=list(state.decision_trace),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("agent_memory_build_failed", error=str(exc))
        return ""


def hypothesize(state: CampaignState, router: LLMRouter) -> list[dict[str, Any]]:
    """Propose N candidate configs. Uses LLM when available; falls back to grid sample."""
    spaces = ensure_spaces(state)
    strategies = list(state.config.strategies)
    n = state.config.proposals_per_generation
    memory = _agent_memory_block(state)
    memory_section = f"\n\n## Prior trial memory\n{memory}\n" if memory else ""
    prompt = (
        f"Propose {n} JSON objects across strategies {strategies} "
        f"with params from spaces {json.dumps(spaces)}. "
        'Return a JSON array of {"strategy","params","rationale"} '
        'and optionally "ingredients" (catalog names only).'
        f"{memory_section}"
        "Use memory to prefer strong regions and avoid weak duplicates; "
        "do not invent indicators outside the campaign strategies."
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
                p.setdefault("strategy", strategies[0])
            return parsed[:n]
    except Exception as exc:
        log.warning("hypothesize_llm_failed", error=str(exc))
    return _sample_multi(
        spaces,
        strategies=strategies,
        n=n,
        seed=state.config.seed + state.generation,
    )


def validate_proposals(
    raw: list[dict[str, Any]],
    state: CampaignState,
    *,
    registry: TrialRegistry | None = None,
) -> list[StrategyProposal]:
    registry = registry or default_registry()
    spaces = ensure_spaces(state)
    valid: list[StrategyProposal] = []
    for item in raw:
        try:
            strat = str(item.get("strategy") or state.config.strategy)
            prop = validate_proposal(
                item,
                search_space=spaces.get(strat),
                registry=registry,
            )
            if strat not in state.config.strategies:
                raise AgentError(f"strategy {strat!r} not in campaign strategies")
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
                initial_cash=float(state.config.initial_cash),
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
                    "generation": state.generation,
                    "initial_cash": metrics.get("initial_cash", state.config.initial_cash),
                    "pnl_mean": metrics.get("pnl_mean"),
                    "pnl_median": metrics.get("pnl_median"),
                    "pnl_mode": metrics.get("pnl_mode"),
                    "pnl_variance": metrics.get("pnl_variance"),
                    "hit_rate": metrics.get("hit_rate"),
                    "net_pnl": metrics.get("net_pnl"),
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
                    "generation": state.generation,
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
    # DSR uses total trial count (multiple-testing across all strategies in campaign)
    n_trials = max(registry.count(), 1)
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
        item = {
            **r,
            "dsr": dsr,
            "pbo": 0.4,
            "verdict": gate.verdict,
        }
        scored.append(item)
        if gate.verdict == "NOISE":
            log.info("shortlist_drop_noise", params=r.get("params"), dsr=dsr)
    keep = [x for x in scored if x.get("verdict") != "NOISE"]
    keep.sort(key=lambda x: float(x.get("sharpe") or -999), reverse=True)
    if not keep and scored:
        scored.sort(key=lambda x: float(x.get("sharpe") or -999), reverse=True)
        return scored[:1]
    return keep[: state.config.shortlist_size]


def score_results(
    results: list[dict[str, Any]],
    state: CampaignState,
    *,
    registry: TrialRegistry | None = None,
) -> list[dict[str, Any]]:
    """Attach DSR/verdict to every successful result (for journals + leaderboard)."""
    registry = registry or default_registry()
    n_trials = max(registry.count(), 1)
    out: list[dict[str, Any]] = []
    for r in results:
        if r.get("sharpe") is None or r.get("error"):
            out.append({**r, "dsr": None, "verdict": "ERROR" if r.get("error") else "NA"})
            continue
        sharpe = float(r["sharpe"])
        dsr = deflated_sharpe(
            sharpe, n_trials=n_trials, n_returns=max((state.config.max_bars or 5000) - 1, 2)
        )
        gate = evaluate_gates(
            dsr=dsr,
            pbo=0.4,
            net_sharpe_1x=sharpe,
            net_sharpe_15x=sharpe,
            cost_drag_pct=float(r.get("cost_drag_pct") or 0.0),
            trade_count=int(r.get("trade_count") or 0),
            holdout_consumed=False,
        )
        out.append({**r, "dsr": dsr, "pbo": 0.4, "verdict": gate.verdict})
    return out


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
    *,
    proposals: list[dict[str, Any]] | None = None,
) -> tuple[str, str, list[dict[str, Any]], dict[str, dict[str, list[Any]]], dict[str, Any]]:
    from fmtrader.agents.apply_ingredients import (
        apply_ingredient_recipe,
        merge_proposal_ingredients,
    )
    from fmtrader.agents.ingredients import (
        list_ingredients,
        parse_ingredients_from_llm_text,
        validate_ingredient_recipe,
    )

    memory = _agent_memory_block(state)
    memory_section = f"\nPrior trial memory (short):\n{memory[:1500]}\n" if memory else ""
    prompt = (
        f"Critique these shortlist results for campaign {state.campaign_id} gen {state.generation}: "
        f"{json.dumps(shortlisted)[:2000]}. Suggest next search space refinement as JSON."
        f"{memory_section}"
    )
    critique = "(stub critique)"
    decision = "Keep top survivors; shrink search space around best params."
    llm_meta: dict[str, Any] = {"critique": {}, "select": {}, "ingredients": {}}
    try:
        out = router.complete(
            prompt,
            purpose="critique",
            campaign_id=state.campaign_id,
            generation=state.generation,
        )
        critique = str(out["text"])[:2000]
        llm_meta["critique"] = {
            "provider": out.get("provider"),
            "model": out.get("model"),
            "cost_usd": out.get("cost_usd"),
        }
    except Exception as exc:
        critique = f"(critique unavailable: {exc})"

    survivors = shortlisted[: state.config.shortlist_size]
    try:
        select_prompt = (
            f"Select up to {state.config.shortlist_size} survivors from "
            f"{json.dumps(shortlisted)[:1500]}. Reply with a short rationale."
            f"{memory_section}"
        )
        sel = router.complete(
            select_prompt,
            purpose="select",
            campaign_id=state.campaign_id,
            generation=state.generation,
            max_tokens=512,
        )
        decision = str(sel["text"])[:1000] or decision
        llm_meta["select"] = {
            "provider": sel.get("provider"),
            "model": sel.get("model"),
            "cost_usd": sel.get("cost_usd"),
        }
    except Exception as exc:
        log.warning("select_llm_failed", error=str(exc))

    ingredient_recipe: dict[str, Any] = {"ingredients": [], "rejected": []}
    if state.config.allow_ingredient_proposals:
        catalog = list_ingredients()
        allowed = [c["name"] for c in catalog if c.get("implemented")]
        try:
            ing_prompt = (
                "Propose experiment ingredients as JSON "
                '{"ingredients":["name",...],"params":{}}. '
                f"Choose only from: {allowed}. Prefer vol_regime_quantile, conformal_filter, "
                "fractional_kelly, fixed_pct_risk, vol_stop when data allows. "
                f"Shortlist context: {json.dumps(shortlisted)[:800]}"
                f"{memory_section}"
                "Use memory of which ingredients co-occurred with better trials."
            )
            ing_out = router.complete(
                ing_prompt,
                purpose="report",
                campaign_id=state.campaign_id,
                generation=state.generation,
                max_tokens=512,
            )
            llm_meta["ingredients"] = {
                "provider": ing_out.get("provider"),
                "model": ing_out.get("model"),
                "cost_usd": ing_out.get("cost_usd"),
            }
            parsed = parse_ingredients_from_llm_text(str(ing_out.get("text") or ""))
            # Dataset capabilities — XAUUSD bid-only today
            has_volume = False
            try:
                from fmtrader.api.deps import get_paths
                from fmtrader.data.ingest import load_manifest

                snap = load_manifest(get_paths().snapshots, state.config.dataset_id)
                has_volume = bool(snap.has_volume)
            except Exception:
                has_volume = False
            validated = validate_ingredient_recipe(
                parsed or {"ingredients": ["vol_regime_quantile", "fractional_kelly"]},
                has_volume=has_volume,
                has_spread=False,
                has_model_artifact=False,
                multi_asset=False,
            )
            ingredient_recipe = validated.recipe
            if proposals:
                ingredient_recipe = merge_proposal_ingredients(
                    ingredient_recipe,
                    proposals,
                    has_volume=has_volume,
                )
            ingredient_recipe = apply_ingredient_recipe(
                state,
                ingredient_recipe,
                results=results,
            )
        except Exception as exc:
            log.warning("ingredient_propose_failed", error=str(exc))
            ingredient_recipe = {
                "ingredients": [],
                "rejected": [{"name": "*", "reason": str(exc)}],
            }

    spaces = {k: dict(v) for k, v in ensure_spaces(state).items()}
    if state.config.refine_space:
        # Shrink each strategy's space around its best survivor params
        by_strat: dict[str, dict[str, Any]] = {}
        for s in survivors:
            name = str(s.get("strategy") or "")
            if name and name not in by_strat:
                by_strat[name] = dict(s.get("params") or {})
        for name, best in by_strat.items():
            space = spaces.get(name)
            if not space:
                continue
            for k, v in best.items():
                if k in space and isinstance(space[k], list) and v in space[k]:
                    vals = space[k]
                    idx = vals.index(v)
                    lo = max(0, idx - 1)
                    hi = min(len(vals), idx + 2)
                    space[k] = vals[lo:hi]
        decision = f"Survivors={len(survivors)}; space refined. " + decision
    else:
        decision = f"Survivors={len(survivors)}; space held open (refine_space=false). " + decision
    return critique, decision, survivors, spaces, {
        "llm": llm_meta,
        "ingredients": ingredient_recipe,
    }


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
    ingredients: dict[str, Any] | None = None,
    llm_meta: dict[str, Any] | None = None,
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
        ingredients=ingredients,
        llm_meta=llm_meta,
    )
    state.journal_paths.append(str(path))
    # Structured trace for UI / APIs
    event = {
        "generation": state.generation,
        "hypothesis": hypothesis,
        "proposals": proposals,
        "results_summary": [
            {
                "strategy": r.get("strategy"),
                "sharpe": r.get("sharpe"),
                "verdict": r.get("verdict"),
                "trade_count": r.get("trade_count"),
            }
            for r in results[:20]
        ],
        "survivors": survivors,
        "critique": critique,
        "decision": decision,
        "ingredients": ingredients or {},
        "llm": llm_meta or {},
        "next_search_space": next_search_space,
        "ingredient_annotations": dict(state.ingredient_annotations or {}),
    }
    # Replace same-generation entry if re-run
    state.decision_trace = [
        e for e in state.decision_trace if int(e.get("generation", -1)) != state.generation
    ]
    state.decision_trace.append(event)
    journal.write_trace_event(state.campaign_id, event)
    return path


def build_leaderboard_summary(state: CampaignState) -> dict[str, Any]:
    rows = [r for r in state.leaderboard if r.get("sharpe") is not None]
    rows.sort(key=lambda x: float(x.get("sharpe") or -999), reverse=True)
    best = rows[0] if rows else None
    by_strategy: dict[str, dict[str, Any]] = {}
    for r in rows:
        name = str(r.get("strategy"))
        if name not in by_strategy:
            by_strategy[name] = r
    why = ""
    if best:
        why = (
            f"Highest net Sharpe among {len(rows)} scored trials "
            f"(DSR={best.get('dsr')}, verdict={best.get('verdict')}, "
            f"cost_drag={best.get('cost_drag_pct')}, trades={best.get('trade_count')}, "
            f"capital={best.get('initial_cash', state.config.initial_cash)}, "
            f"pnl_mean={best.get('pnl_mean')}, pnl_median={best.get('pnl_median')}, "
            f"pnl_mode={best.get('pnl_mode')}, pnl_var={best.get('pnl_variance')}). "
            "PBO is a conservative placeholder (0.4) until CSCV runs on fidelity lane."
        )
    return {
        "n_trials": len(state.leaderboard),
        "n_scored": len(rows),
        "initial_cash": state.config.initial_cash,
        "best_overall": best,
        "best_by_strategy": by_strategy,
        "why": why,
        "top10": rows[:10],
    }
