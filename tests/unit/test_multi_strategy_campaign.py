"""Multi-strategy campaign + leaderboard summary."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml

from fmtrader.agents.campaign import CampaignConfig, bind_search_spaces, load_search_spaces
from fmtrader.agents.journal import ResearchJournal
from fmtrader.agents.runner import CampaignStore, create_campaign, run_campaign_local


def test_load_multi_family_spaces() -> None:
    spaces = load_search_spaces(Path("configs/spaces/multi_family.yaml"))
    assert "ema_cross" in spaces
    assert "rsi_mean_reversion" in spaces
    bound = bind_search_spaces(
        spaces,
        ["ema_cross", "rsi_mean_reversion", "macd_cross", "bollinger_breakout", "supertrend_trend"],
    )
    assert set(bound) == {
        "ema_cross",
        "rsi_mean_reversion",
        "macd_cross",
        "bollinger_breakout",
        "supertrend_trend",
    }


def test_multi_campaign_leaderboard(tmp_path: Path) -> None:
    space = tmp_path / "multi.yaml"
    space.write_text(
        yaml.dump(
            {
                "strategies": {
                    "ema_cross": {"fast": [5], "slow": [20]},
                    "rsi_mean_reversion": {
                        "period": [14],
                        "oversold": [30],
                        "overbought": [70],
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    cfg_path = tmp_path / "camp.yaml"
    cfg_path.write_text(
        yaml.dump(
            {
                "name": "multi",
                "dataset_id": "xauusd_1m_bid_2021-01-03_2026-08-30",
                "strategies": ["ema_cross", "rsi_mean_reversion"],
                "space_path": str(space),
                "max_generations": 1,
                "proposals_per_generation": 2,
                "shortlist_size": 2,
                "max_bars": 500,
                "use_stub_llm": True,
                "run_fidelity": False,
                "budget": {
                    "per_campaign_usd": 1.0,
                    "per_day_usd": 1.0,
                    "per_generation_usd": 1.0,
                },
            }
        ),
        encoding="utf-8",
    )
    cfg = CampaignConfig.from_yaml(cfg_path)
    assert cfg.strategies == ["ema_cross", "rsi_mean_reversion"]

    def _fake_sweep(proposals, state):
        out = []
        for i, p in enumerate(proposals):
            out.append(
                {
                    "strategy": p.strategy,
                    "params": p.params,
                    "sharpe": 1.0 - i * 0.1,
                    "total_return_net": 0.01,
                    "trade_count": 10,
                    "cost_drag_pct": 5.0,
                    "lane": "vectorbt",
                    "generation": state.generation,
                }
            )
        return out

    store = CampaignStore(root=tmp_path / "campaigns")
    journal = ResearchJournal(root=tmp_path / "journals")
    state = create_campaign(cfg, store=store)
    with patch("fmtrader.agents.runner.fast_sweep", side_effect=_fake_sweep):
        state = run_campaign_local(state, store=store, journal=journal, max_generations=1)

    assert state.status == "completed"
    assert len(state.leaderboard) >= 1
    summary = journal.campaign_dir(state.campaign_id) / "SUMMARY.md"
    assert summary.exists()
    text = summary.read_text(encoding="utf-8")
    assert "Best overall" in text
    assert "Leaderboard" in text
