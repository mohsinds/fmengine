"""Slim Temporal activity payload tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import yaml

from fmtrader.agents.campaign import CampaignConfig
from fmtrader.agents.runner import CampaignStore, create_campaign
from fmtrader.orchestration.activities import (
    _slim,
    load_campaign_snapshot_activity,
    run_generation_activity,
)


def test_slim_excludes_leaderboard(tmp_path: Path) -> None:
    space = tmp_path / "space.yaml"
    space.write_text(yaml.dump({"grid": {"fast": [5], "slow": [20]}}), encoding="utf-8")
    cfg = CampaignConfig(
        name="t",
        dataset_id="xauusd_1m_bid_2021-01-03_2026-08-30",
        strategy="ema_cross",
        space_path=str(space),
        max_generations=2,
        use_stub_llm=True,
    )
    store = CampaignStore(root=tmp_path / "campaigns")
    state = create_campaign(cfg, store=store)
    state.leaderboard = [{"strategy": "ema_cross", "sharpe": 1.0, "params": {"fast": 5}}] * 50
    store.save(state)
    slim = _slim(state)
    assert "leaderboard" not in slim
    assert slim["leaderboard_count"] == 50
    assert slim["campaign_id"] == state.campaign_id


def test_run_generation_activity_loads_from_store(tmp_path: Path) -> None:
    space = tmp_path / "space.yaml"
    space.write_text(yaml.dump({"grid": {"fast": [5], "slow": [20]}}), encoding="utf-8")
    cfg = CampaignConfig(
        name="t",
        dataset_id="xauusd_1m_bid_2021-01-03_2026-08-30",
        strategy="ema_cross",
        space_path=str(space),
        max_generations=2,
        proposals_per_generation=1,
        use_stub_llm=True,
        max_bars=500,
    )
    store = CampaignStore(root=tmp_path / "campaigns")
    state = create_campaign(cfg, store=store)

    def _fake_run(st, *, router, journal=None):
        st.generation += 1
        st.status = "running"
        st.leaderboard.append({"strategy": "ema_cross", "sharpe": 0.1})
        return st

    with (
        patch("fmtrader.orchestration.activities.CampaignStore", return_value=store),
        patch("fmtrader.orchestration.activities.run_generation", side_effect=_fake_run),
    ):
        out = asyncio.run(run_generation_activity({"campaign_id": state.campaign_id}))
    assert out["generation"] == 1
    assert "leaderboard" not in out
    loaded = store.load(state.campaign_id)
    assert loaded.generation == 1
    assert len(loaded.leaderboard) == 1


def test_load_snapshot_activity(tmp_path: Path) -> None:
    space = tmp_path / "space.yaml"
    space.write_text(yaml.dump({"grid": {"fast": [5], "slow": [20]}}), encoding="utf-8")
    cfg = CampaignConfig(
        name="t",
        dataset_id="ds",
        strategy="ema_cross",
        space_path=str(space),
    )
    store = CampaignStore(root=tmp_path / "campaigns")
    state = create_campaign(cfg, store=store)
    with patch("fmtrader.orchestration.activities.CampaignStore", return_value=store):
        snap = asyncio.run(load_campaign_snapshot_activity(state.campaign_id))
    assert snap["campaign_id"] == state.campaign_id
    assert snap["generation"] == 0
