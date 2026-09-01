"""Campaign configuration and mutable state."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from fmtrader.agents.budget import BudgetCaps
from fmtrader.core.errors import AgentError


class CampaignConfig(BaseModel):
    name: str = "campaign"
    dataset_id: str
    strategy: str = "ema_cross"
    space_path: str = "configs/spaces/ema_cross.yaml"
    max_generations: int = 3
    proposals_per_generation: int = 5
    shortlist_size: int = 2
    max_sweep_configs: int = 20
    workers: int = 2
    max_bars: int | None = 5000
    cost_config: str = "configs/costs/xauusd_cfd.yaml"
    run_fidelity: bool = False
    budget: BudgetCaps = Field(default_factory=BudgetCaps)
    seed: int = 0
    use_stub_llm: bool = True

    @classmethod
    def from_yaml(cls, path: Path) -> CampaignConfig:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise AgentError(f"Campaign config must be a mapping: {path}")
        budget = data.pop("budget", {}) or {}
        if budget:
            data["budget"] = BudgetCaps(
                per_campaign_usd=float(budget.get("per_campaign_usd", 0) or 0),
                per_day_usd=float(budget.get("per_day_usd", 0) or 0),
                per_generation_usd=float(budget.get("per_generation_usd", 0) or 0),
            )
        return cls.model_validate(data)


CampaignStatus = Literal[
    "created",
    "running",
    "paused",
    "completed",
    "aborted",
    "failed",
]


@dataclass
class CampaignState:
    campaign_id: str
    config: CampaignConfig
    status: CampaignStatus = "created"
    generation: int = 0
    search_space: dict[str, list[Any]] = field(default_factory=dict)
    survivors: list[dict[str, Any]] = field(default_factory=list)
    journal_paths: list[str] = field(default_factory=list)
    last_error: str | None = None
    pause_requested: bool = False
    abort_requested: bool = False
    budget_override: BudgetCaps | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "status": self.status,
            "generation": self.generation,
            "config": self.config.model_dump(),
            "search_space": self.search_space,
            "survivors": self.survivors,
            "journal_paths": self.journal_paths,
            "last_error": self.last_error,
            "pause_requested": self.pause_requested,
            "abort_requested": self.abort_requested,
            "budget_override": (
                None
                if self.budget_override is None
                else {
                    "per_campaign_usd": self.budget_override.per_campaign_usd,
                    "per_day_usd": self.budget_override.per_day_usd,
                    "per_generation_usd": self.budget_override.per_generation_usd,
                }
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CampaignState:
        cfg = CampaignConfig.model_validate(data["config"])
        bo = data.get("budget_override")
        return cls(
            campaign_id=str(data["campaign_id"]),
            config=cfg,
            status=data.get("status", "created"),
            generation=int(data.get("generation", 0)),
            search_space=dict(data.get("search_space") or {}),
            survivors=list(data.get("survivors") or []),
            journal_paths=list(data.get("journal_paths") or []),
            last_error=data.get("last_error"),
            pause_requested=bool(data.get("pause_requested", False)),
            abort_requested=bool(data.get("abort_requested", False)),
            budget_override=BudgetCaps(**bo) if isinstance(bo, dict) else None,
        )


def load_search_space(path: Path) -> dict[str, list[Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    grid = data.get("grid") or data
    if not isinstance(grid, dict):
        raise AgentError(f"Search space must be a mapping: {path}")
    out: dict[str, list[Any]] = {}
    for k, v in grid.items():
        if isinstance(v, list):
            out[str(k)] = list(v)
    return out
