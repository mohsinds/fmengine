"""Campaign configuration and mutable state."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from fmtrader.agents.budget import BudgetCaps
from fmtrader.agents.routing import LLMRoutingConfig
from fmtrader.core.errors import AgentError


class CampaignConfig(BaseModel):
    name: str = "campaign"
    dataset_id: str
    strategy: str = "ema_cross"
    """Primary strategy (backward compatible). Used when ``strategies`` is empty."""

    strategies: list[str] = Field(default_factory=list)
    """When set, campaign proposes across this list (multi-strategy search)."""

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
    refine_space: bool = True
    """When False, keep full search grids across generations (long exhaustive soaks)."""

    initial_cash: float = 100_000.0
    """Paper capital used for backtest sizing / P&L reporting."""

    llm_routing: LLMRoutingConfig = Field(default_factory=LLMRoutingConfig)
    """Per-purpose provider/model map (Ollama local by default)."""

    allow_ingredient_proposals: bool = True
    """When True, critique/select may propose curated experiment ingredients."""

    use_agent_memory: bool = True
    """Inject trial-registry + journal retrieval into hypothesize/critique/ingredient prompts."""

    @model_validator(mode="after")
    def _normalize_strategies(self) -> CampaignConfig:
        if not self.strategies:
            object.__setattr__(self, "strategies", [self.strategy])
        elif self.strategy not in self.strategies:
            # Keep strategy as first listed for stub/LLM defaults
            object.__setattr__(self, "strategy", self.strategies[0])
        return self

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
                openai_usd=float(budget.get("openai_usd", 0) or 0),
                anthropic_usd=float(budget.get("anthropic_usd", 0) or 0),
            )
        routing = data.pop("llm_routing", None)
        if routing is not None:
            data["llm_routing"] = LLMRoutingConfig.from_mapping(
                routing if isinstance(routing, dict) else {}
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
    """Flat space for the primary strategy (compat). Prefer ``search_spaces``."""

    search_spaces: dict[str, dict[str, list[Any]]] = field(default_factory=dict)
    survivors: list[dict[str, Any]] = field(default_factory=list)
    leaderboard: list[dict[str, Any]] = field(default_factory=list)
    """Accumulated scored trials across generations (for end-of-campaign summary)."""

    journal_paths: list[str] = field(default_factory=list)
    last_error: str | None = None
    pause_requested: bool = False
    abort_requested: bool = False
    budget_override: BudgetCaps | None = None
    active_ingredients: list[str] = field(default_factory=list)
    """Accepted ingredient names for the latest generation."""

    ingredient_annotations: dict[str, Any] = field(default_factory=dict)
    """Applied sizing/regime/stop annotations from the latest ingredient recipe."""

    decision_trace: list[dict[str, Any]] = field(default_factory=list)
    """Structured per-generation decisions for the progress UI / APIs."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "status": self.status,
            "generation": self.generation,
            "config": self.config.model_dump(),
            "search_space": self.search_space,
            "search_spaces": self.search_spaces,
            "survivors": self.survivors,
            "leaderboard": self.leaderboard,
            "journal_paths": self.journal_paths,
            "last_error": self.last_error,
            "pause_requested": self.pause_requested,
            "abort_requested": self.abort_requested,
            "active_ingredients": self.active_ingredients,
            "ingredient_annotations": self.ingredient_annotations,
            "decision_trace": self.decision_trace,
            "budget_override": (
                None
                if self.budget_override is None
                else {
                    "per_campaign_usd": self.budget_override.per_campaign_usd,
                    "per_day_usd": self.budget_override.per_day_usd,
                    "per_generation_usd": self.budget_override.per_generation_usd,
                    "openai_usd": self.budget_override.openai_usd,
                    "anthropic_usd": self.budget_override.anthropic_usd,
                }
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CampaignState:
        cfg_raw = dict(data["config"])
        if "llm_routing" in cfg_raw and isinstance(cfg_raw["llm_routing"], dict):
            cfg_raw["llm_routing"] = LLMRoutingConfig.from_mapping(cfg_raw["llm_routing"])
        cfg = CampaignConfig.model_validate(cfg_raw)
        bo = data.get("budget_override")
        spaces = dict(data.get("search_spaces") or {})
        flat = dict(data.get("search_space") or {})
        if not spaces and flat:
            spaces = {cfg.strategy: flat}
        return cls(
            campaign_id=str(data["campaign_id"]),
            config=cfg,
            status=data.get("status", "created"),
            generation=int(data.get("generation", 0)),
            search_space=flat,
            search_spaces=spaces,
            survivors=list(data.get("survivors") or []),
            leaderboard=list(data.get("leaderboard") or []),
            journal_paths=list(data.get("journal_paths") or []),
            last_error=data.get("last_error"),
            pause_requested=bool(data.get("pause_requested", False)),
            abort_requested=bool(data.get("abort_requested", False)),
            budget_override=BudgetCaps(**bo) if isinstance(bo, dict) else None,
            active_ingredients=list(data.get("active_ingredients") or []),
            ingredient_annotations=dict(data.get("ingredient_annotations") or {}),
            decision_trace=list(data.get("decision_trace") or []),
        )


def _coerce_grid(grid: object) -> dict[str, list[Any]]:
    if not isinstance(grid, dict):
        raise AgentError("Search space grid must be a mapping")
    out: dict[str, list[Any]] = {}
    for k, v in grid.items():
        if isinstance(v, list):
            out[str(k)] = list(v)
    return out


def load_search_space(path: Path) -> dict[str, list[Any]]:
    """Load a flat grid (primary strategy). Multi-strategy files return the first strategy's grid."""
    spaces = load_search_spaces(path)
    if not spaces:
        return {}
    # Prefer explicit primary name if present in file metadata — else first key
    return next(iter(spaces.values()))


def load_search_spaces(path: Path) -> dict[str, dict[str, list[Any]]]:
    """Load per-strategy grids.

    Formats:
    - ``{grid: {...}}`` — single unnamed grid (caller binds to campaign strategy)
    - ``{strategies: {name: {param: [...]}}}`` — multi-strategy
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise AgentError(f"Search space must be a mapping: {path}")
    if "strategies" in data and isinstance(data["strategies"], dict):
        out: dict[str, dict[str, list[Any]]] = {}
        for name, grid in data["strategies"].items():
            out[str(name)] = _coerce_grid(grid)
        return out
    grid = data.get("grid") or data
    # Strip non-grid metadata keys
    if isinstance(grid, dict):
        grid = {k: v for k, v in grid.items() if k not in {"name", "strategies"} and isinstance(v, list)}
    return {"__default__": _coerce_grid(grid)}


def bind_search_spaces(
    spaces: dict[str, dict[str, list[Any]]],
    strategies: list[str],
) -> dict[str, dict[str, list[Any]]]:
    """Map loaded spaces onto the campaign strategy list."""
    if "__default__" in spaces and len(spaces) == 1:
        default = spaces["__default__"]
        if len(strategies) == 1:
            return {strategies[0]: default}
        # Same flat grid applied only makes sense for one strategy family;
        # multi-strategy campaigns must use an explicit strategies: block.
        raise AgentError(
            "Multi-strategy campaign requires space YAML with a 'strategies:' map "
            f"(got flat grid for strategies={strategies})"
        )
    missing = [s for s in strategies if s not in spaces]
    if missing:
        raise AgentError(f"Search space missing strategies: {missing}; have {sorted(spaces)}")
    return {s: spaces[s] for s in strategies}
