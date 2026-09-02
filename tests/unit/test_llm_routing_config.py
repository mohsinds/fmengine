"""Unit tests for LLM routing config and ingredient catalog."""

from __future__ import annotations

from fmtrader.agents.budget import BudgetCaps, BudgetGovernor
from fmtrader.agents.ingredients import validate_ingredient_recipe
from fmtrader.agents.ledger import CostLedger
from fmtrader.agents.llm import LLMRouter, StubLLMClient, default_router
from fmtrader.agents.routing import LLMRoutingConfig


def test_default_routing_is_all_local() -> None:
    cfg = LLMRoutingConfig()
    assert cfg.hypothesize.provider == "ollama"
    assert cfg.critique.provider == "ollama"
    assert "14b" in cfg.critique.model


def test_routing_from_mapping_cloud_override() -> None:
    cfg = LLMRoutingConfig.from_mapping(
        {
            "critique": {"provider": "anthropic", "model": "claude-sonnet-4-5-20250929"},
            "report": {"provider": "openai", "model": "gpt-4o-mini"},
        }
    )
    assert cfg.critique.provider == "anthropic"
    assert cfg.report.provider == "openai"
    assert cfg.hypothesize.provider == "ollama"


def test_router_uses_purpose_clients(tmp_path) -> None:
    gov = BudgetGovernor(BudgetCaps(), ledger=CostLedger(tmp_path))
    clients = {
        "hypothesize": StubLLMClient(provider="stub", model="h", response="[]"),
        "critique": StubLLMClient(provider="stub", model="c", response="critique"),
        "select": StubLLMClient(provider="stub", model="s", response="select"),
        "report": StubLLMClient(provider="stub", model="r", response='{"ingredients":[]}'),
    }
    r = LLMRouter(gov, purpose_clients=clients, sweep_active=True)
    out = r.complete("hi", purpose="critique", campaign_id="c1", generation=1)
    assert out["model"] == "c"
    assert out["text"] == "critique"


def test_ingredient_rejects_hawkes_without_volume() -> None:
    v = validate_ingredient_recipe(
        {"ingredients": ["hawkes_clustering", "fractional_kelly", "nope"]},
        has_volume=False,
    )
    assert "fractional_kelly" in v.accepted
    assert "hawkes_clustering" not in v.accepted
    reasons = {r["name"]: r["reason"] for r in v.rejected}
    assert "hawkes_clustering" in reasons
    assert "nope" in reasons


def test_ingredient_accepts_vol_tools() -> None:
    v = validate_ingredient_recipe(
        {
            "ingredients": [
                "vol_regime_quantile",
                "conformal_filter",
                "fractional_kelly",
                "fixed_pct_risk",
                "vol_stop",
            ]
        },
        has_volume=False,
    )
    assert len(v.accepted) == 5
    assert v.rejected == []


def test_default_router_stub_still_works() -> None:
    r = default_router(stub=True)
    assert isinstance(r, LLMRouter)
