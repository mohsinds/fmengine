"""Budget governor unit tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from fmtrader.agents.budget import BudgetCaps, BudgetGovernor, CallEstimate
from fmtrader.agents.ledger import CostLedger
from fmtrader.core.errors import BudgetError


def _est(*, cost: float, tier: str = "F") -> CallEstimate:
    return CallEstimate(
        provider="anthropic" if tier == "F" else "ollama",
        model="test",
        tier=tier,  # type: ignore[arg-type]
        purpose="critique",
        estimated_prompt_tokens=1000,
        estimated_completion_tokens=500,
        estimated_cost_usd=cost,
    )


def test_refuses_call_that_would_breach_campaign_cap(tmp_path: Path) -> None:
    ledger = CostLedger(tmp_path)
    gov = BudgetGovernor(
        BudgetCaps(per_campaign_usd=1.0), ledger=ledger, allow_degrade_to_local=False
    )
    gov.record_success(
        campaign_id="c1",
        generation=0,
        provider="anthropic",
        model="x",
        tier="F",
        purpose="critique",
        prompt_tokens=100,
        completion_tokens=100,
        cost_usd=0.9,
    )
    d = gov.authorize(_est(cost=0.2), campaign_id="c1", generation=1)
    assert d.allowed is False
    with pytest.raises(BudgetError):
        gov.require(d)


def test_refuses_call_that_would_breach_daily_cap(tmp_path: Path) -> None:
    ledger = CostLedger(tmp_path)
    gov = BudgetGovernor(BudgetCaps(per_day_usd=0.5), ledger=ledger, allow_degrade_to_local=False)
    gov.record_success(
        campaign_id="c1",
        generation=0,
        provider="anthropic",
        model="x",
        tier="F",
        purpose="critique",
        prompt_tokens=10,
        completion_tokens=10,
        cost_usd=0.4,
    )
    d = gov.authorize(_est(cost=0.2), campaign_id="c2", generation=0)
    assert d.allowed is False


def test_degrades_to_local_tier_on_exhaustion_without_crashing(tmp_path: Path) -> None:
    ledger = CostLedger(tmp_path)
    gov = BudgetGovernor(
        BudgetCaps(per_campaign_usd=0.1), ledger=ledger, allow_degrade_to_local=True
    )
    gov.record_success(
        campaign_id="c1",
        generation=0,
        provider="anthropic",
        model="x",
        tier="F",
        purpose="critique",
        prompt_tokens=10,
        completion_tokens=10,
        cost_usd=0.1,
    )
    d = gov.authorize(_est(cost=1.0, tier="F"), campaign_id="c1", generation=1)
    assert d.allowed is True
    assert d.degraded is True
    assert d.tier == "L"


def test_ledger_records_every_call(tmp_path: Path) -> None:
    ledger = CostLedger(tmp_path)
    gov = BudgetGovernor(BudgetCaps(), ledger=ledger)
    gov.record_success(
        campaign_id="c1",
        generation=1,
        provider="stub",
        model="s",
        tier="L",
        purpose="hypothesize",
        prompt_tokens=10,
        completion_tokens=5,
        cost_usd=0.0,
    )
    assert ledger.count(campaign_id="c1") == 1


def test_cost_estimate_precedes_call(tmp_path: Path) -> None:
    ledger = CostLedger(tmp_path)
    gov = BudgetGovernor(
        BudgetCaps(per_generation_usd=0.01), ledger=ledger, allow_degrade_to_local=False
    )
    # Authorize (estimate) before any success record
    d = gov.authorize(_est(cost=1.0), campaign_id="c1", generation=0)
    assert d.allowed is False
    # Refusal is ledgered with cost 0
    assert ledger.count(campaign_id="c1") == 1
    rows = ledger.list_entries("c1")
    assert rows[0]["refused"] == 1
