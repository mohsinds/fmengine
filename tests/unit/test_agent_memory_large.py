"""Unit tests for agent memory, ollama_cloud routing, and ingredient apply."""

from __future__ import annotations

from pathlib import Path

from fmtrader.agents.apply_ingredients import apply_ingredient_recipe, merge_proposal_ingredients
from fmtrader.agents.campaign import CampaignConfig, CampaignState
from fmtrader.agents.memory import build_agent_memory, summarize_trials
from fmtrader.agents.routing import LLMRoutingConfig, is_heavy_ollama_model, large_agent_routing
from fmtrader.backtest.validation.registry import TrialRecord


def test_ollama_cloud_routing_from_mapping() -> None:
    cfg = LLMRoutingConfig.from_mapping(
        {
            "critique": {
                "provider": "ollama_cloud",
                "model": "kimi-k2.6:cloud",
                "fallback": {"provider": "ollama", "model": "qwen3.8:27b"},
            }
        }
    )
    assert cfg.critique.provider == "ollama_cloud"
    assert cfg.critique.model == "kimi-k2.6:cloud"
    assert cfg.critique.fallback is not None
    assert cfg.critique.fallback.model == "qwen3.8:27b"


def test_large_agent_routing_layer_map() -> None:
    cfg = large_agent_routing()
    assert cfg.hypothesize.model == "gpt-oss:20b"
    assert cfg.critique.provider == "ollama_cloud"
    assert cfg.report.model == "qwen3.8:27b"
    assert is_heavy_ollama_model("gpt-oss:20b")
    assert is_heavy_ollama_model("qwen3.8:27b")
    assert not is_heavy_ollama_model("qwen2.5-coder:7b")


def test_summarize_trials_ranks_by_sharpe() -> None:
    trials = [
        TrialRecord(
            config_hash="a",
            strategy="ema_cross",
            params={"fast": 10},
            metrics={"sharpe": 0.1, "cost_drag_pct": 40.0},
            source="agent",
            dataset_id="ds1",
            lane="vectorbt",
        ),
        TrialRecord(
            config_hash="b",
            strategy="ema_cross",
            params={"fast": 20},
            metrics={"sharpe": 1.5, "cost_drag_pct": 10.0, "verdict": "promote"},
            source="sweep",
            dataset_id="ds1",
            lane="vectorbt",
        ),
    ]
    text = summarize_trials(trials, strategies=["ema_cross"], limit=10)
    assert "Strong prior" in text
    assert text.index("fast\": 20") < text.index("fast\": 10")


def test_build_agent_memory_includes_decision_trace(tmp_path: Path) -> None:
    text = build_agent_memory(
        dataset_id="ds1",
        strategies=["ema_cross"],
        registry_path=tmp_path / "missing.sqlite",
        journal_root=tmp_path / "journals",
        decision_trace=[
            {
                "generation": 1,
                "ingredients": {"ingredients": ["fractional_kelly"]},
                "decision": "keep survivors",
            }
        ],
    )
    assert "ema_cross" in text
    assert "fractional_kelly" in text
    assert "keep survivors" in text


def test_apply_ingredient_recipe_marks_state() -> None:
    state = CampaignState(
        campaign_id="c1",
        config=CampaignConfig(name="t", dataset_id="ds1", use_stub_llm=True),
    )
    results = [{"strategy": "ema_cross", "sharpe": 0.5}]
    out = apply_ingredient_recipe(
        state,
        {
            "ingredients": [
                "fractional_kelly",
                "vol_regime_quantile",
                "conformal_filter",
                "hawkes_clustering",
            ],
            "params": {"kelly_fraction": 0.2},
        },
        results=results,
    )
    assert "fractional_kelly" in out["ingredients"]
    assert "vol_regime_quantile" in out["ingredients"]
    assert "conformal_filter" not in out["ingredients"]
    assert state.ingredient_annotations["sizing"]["method"] == "fractional_kelly"
    assert results[0]["ingredients"] == state.active_ingredients
    deferred_names = {r["name"] for r in out["rejected"] if isinstance(r, dict)}
    assert "conformal_filter" in deferred_names


def test_merge_proposal_ingredients() -> None:
    recipe = merge_proposal_ingredients(
        {"ingredients": ["vol_stop"], "params": {}},
        [{"ingredients": ["fractional_kelly"]}, {"ingredients": ["hawkes_clustering"]}],
        has_volume=False,
    )
    assert "vol_stop" in recipe["ingredients"]
    assert "fractional_kelly" in recipe["ingredients"]
    assert "hawkes_clustering" not in recipe["ingredients"]


def test_campaign_yaml_large_loads() -> None:
    cfg = CampaignConfig.from_yaml(Path("configs/campaigns/trial_agentic_large.yaml"))
    assert cfg.use_agent_memory is True
    assert cfg.workers == 2
    assert cfg.llm_routing.hypothesize.model == "gpt-oss:20b"
    assert cfg.llm_routing.critique.provider == "ollama_cloud"


def test_hypothesize_prompt_includes_memory(monkeypatch) -> None:
    from fmtrader.agents import nodes
    from fmtrader.agents.budget import BudgetCaps, BudgetGovernor
    from fmtrader.agents.ledger import CostLedger
    from fmtrader.agents.llm import LLMRouter, StubLLMClient
    import fmtrader.agents.memory as mem

    captured: list[str] = []

    class CaptureStub(StubLLMClient):
        def complete(self, prompt: str, *, max_tokens: int = 1024) -> tuple[str, int, int]:
            captured.append(prompt)
            return "[]", 1, 1

    state = CampaignState(
        campaign_id="c-mem",
        config=CampaignConfig(
            name="t",
            dataset_id="ds1",
            use_stub_llm=True,
            use_agent_memory=True,
            proposals_per_generation=2,
        ),
    )
    state.search_spaces = {"ema_cross": {"fast": [5, 10]}}
    state.decision_trace = [
        {
            "generation": 0,
            "ingredients": {"ingredients": ["vol_stop"]},
            "decision": "prior decision note",
        }
    ]
    monkeypatch.setattr(
        mem,
        "build_agent_memory",
        lambda **kwargs: "MEMORY_STUB_BLOCK prior decision note",
    )
    gov = BudgetGovernor(BudgetCaps(), ledger=CostLedger())
    router = LLMRouter(
        gov,
        purpose_clients={"hypothesize": CaptureStub(response="[]")},
        sweep_active=False,
    )
    nodes.hypothesize(state, router)
    assert captured
    assert "MEMORY_STUB_BLOCK" in captured[0]