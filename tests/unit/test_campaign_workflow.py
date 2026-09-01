"""In-process campaign workflow tests (backtest mocked for speed)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from fmtrader.agents.campaign import CampaignConfig
from fmtrader.agents.journal import ResearchJournal
from fmtrader.agents.runner import (
    CampaignStore,
    create_campaign,
    run_campaign_local,
    signal_abort,
    signal_pause,
    signal_resume,
)


@pytest.fixture()
def short_config(tmp_path: Path) -> Path:
    space = tmp_path / "space.yaml"
    space.write_text(
        yaml.dump({"grid": {"fast": [5, 8], "slow": [20, 30]}}),
        encoding="utf-8",
    )
    cfg = {
        "name": "test",
        "dataset_id": "xauusd_1m_bid_2021-01-03_2026-08-30",
        "strategy": "ema_cross",
        "space_path": str(space),
        "max_generations": 2,
        "proposals_per_generation": 2,
        "shortlist_size": 1,
        "max_bars": 2000,
        "cost_config": "configs/costs/xauusd_cfd.yaml",
        "use_stub_llm": True,
        "run_fidelity": False,
        "budget": {"per_campaign_usd": 1.0, "per_day_usd": 1.0, "per_generation_usd": 1.0},
    }
    path = tmp_path / "campaign.yaml"
    path.write_text(yaml.dump(cfg), encoding="utf-8")
    return path


def _fake_sweep(proposals, state):
    out = []
    for i, p in enumerate(proposals):
        out.append(
            {
                "strategy": p.strategy,
                "params": p.params,
                "execution_id": f"fake-{i}",
                "sharpe": 1.0 - 0.1 * i,
                "total_return_net": 0.01,
                "trade_count": 40,
                "cost_drag_pct": 5.0,
                "lane": "vectorbt",
            }
        )
    return out


def test_campaign_completes_short_run(short_config: Path, tmp_path: Path) -> None:
    store = CampaignStore(tmp_path / "campaigns")
    journal = ResearchJournal(tmp_path / "journals")
    cfg = CampaignConfig.from_yaml(short_config)
    state = create_campaign(cfg, store=store)
    with patch("fmtrader.agents.nodes.fast_sweep", side_effect=_fake_sweep):
        state = run_campaign_local(state, store=store, journal=journal)
    assert state.status == "completed"
    assert state.generation == 2
    report = journal.read_report(state.campaign_id)
    assert "Generation" in report


def test_pause_signal_halts_after_current_activity(short_config: Path, tmp_path: Path) -> None:
    store = CampaignStore(tmp_path / "campaigns")
    cfg = CampaignConfig.from_yaml(short_config)
    state = create_campaign(cfg, store=store)
    signal_pause(state.campaign_id, store=store)
    state = store.load(state.campaign_id)
    assert state.pause_requested is True
    with patch("fmtrader.agents.nodes.fast_sweep", side_effect=_fake_sweep):
        state = run_campaign_local(state, store=store, journal=ResearchJournal(tmp_path / "j"))
    assert state.status == "paused"
    assert state.generation == 0


def test_resume_continues_from_checkpoint(short_config: Path, tmp_path: Path) -> None:
    store = CampaignStore(tmp_path / "campaigns")
    journal = ResearchJournal(tmp_path / "journals")
    cfg = CampaignConfig.from_yaml(short_config)
    state = create_campaign(cfg, store=store)
    from fmtrader.agents.budget import BudgetCaps, BudgetGovernor
    from fmtrader.agents.ledger import CostLedger
    from fmtrader.agents.llm import LLMRouter
    from fmtrader.agents.runner import run_generation

    router = LLMRouter(BudgetGovernor(BudgetCaps(), CostLedger(tmp_path / "led")))
    state.status = "running"
    with patch("fmtrader.agents.nodes.fast_sweep", side_effect=_fake_sweep):
        state = run_generation(state, router=router, journal=journal)
        store.save(state)
        assert state.generation == 1
        signal_pause(state.campaign_id, store=store)
        state = signal_resume(state.campaign_id, store=store)
    assert state.status == "completed"
    assert state.generation == 2


def test_abort_leaves_consistent_state(short_config: Path, tmp_path: Path) -> None:
    store = CampaignStore(tmp_path / "campaigns")
    cfg = CampaignConfig.from_yaml(short_config)
    state = create_campaign(cfg, store=store)
    state = signal_abort(state.campaign_id, store=store)
    assert state.status == "aborted"
    assert store.load(state.campaign_id).status == "aborted"


def test_journal_written_per_generation(short_config: Path, tmp_path: Path) -> None:
    store = CampaignStore(tmp_path / "campaigns")
    journal = ResearchJournal(tmp_path / "journals")
    cfg = CampaignConfig.from_yaml(short_config)
    cfg = cfg.model_copy(update={"max_generations": 1})
    state = create_campaign(cfg, store=store)
    with patch("fmtrader.agents.nodes.fast_sweep", side_effect=_fake_sweep):
        state = run_campaign_local(state, store=store, journal=journal)
    files = list((tmp_path / "journals" / state.campaign_id).glob("generation_*.md"))
    assert len(files) == 1


def test_agent_cannot_reach_holdout() -> None:
    from fmtrader.agents.proposals import validate_proposal
    from fmtrader.core.errors import AgentError

    with pytest.raises(AgentError, match="holdout"):
        validate_proposal(
            {
                "strategy": "ema_cross",
                "params": {"fast": 5, "slow": 20},
                "rationale": "read HoldoutUnlockToken",
            },
            allow_unknown_strategy=True,
        )
