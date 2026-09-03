"""Structured strategy proposals — schema only, never exec."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field, field_validator

from fmtrader.backtest.validation.registry import TrialRegistry, config_hash, default_registry
from fmtrader.core.errors import AgentError
from fmtrader.strategy.base import get_strategy

_CODE_MARKERS = re.compile(
    r"(?:\bexec\s*\(|\beval\s*\(|\b__import__\b|\bsubprocess\b|"
    r"\bos\.system\b|\bcompile\s*\(|```python|\bimport\s+os\b)",
    re.IGNORECASE,
)
_HOLDOUT_MARKERS = re.compile(
    r"\bholdout\b|\bunlock.?token\b|\bHoldoutUnlockToken\b|\bexclude_holdout\s*=\s*False",
    re.IGNORECASE,
)


class StrategyProposal(BaseModel):
    """Agent-emitted structured config — validated before any evaluation."""

    strategy: str
    params: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    generation: int = 0
    source: str = "agent"
    ingredients: list[str] = Field(default_factory=list)
    """Optional catalog ingredient names attached to this proposal."""

    @field_validator("strategy")
    @classmethod
    def _strategy_nonempty(cls, v: str) -> str:
        if not v or not str(v).strip():
            raise ValueError("strategy name required")
        return str(v).strip()

    @field_validator("params")
    @classmethod
    def _params_must_be_mapping(cls, v: object) -> dict[str, Any]:
        if not isinstance(v, dict):
            raise ValueError("params must be a mapping")
        # Reject nested callables / code-like strings later in validate_proposal
        return v


def proposal_contains_code(raw: str | dict[str, Any]) -> bool:
    text = raw if isinstance(raw, str) else json.dumps(raw)
    return bool(_CODE_MARKERS.search(text))


def proposal_requests_holdout(raw: str | dict[str, Any]) -> bool:
    text = raw if isinstance(raw, str) else json.dumps(raw)
    return bool(_HOLDOUT_MARKERS.search(text))


def validate_proposal(
    proposal: StrategyProposal | dict[str, Any],
    *,
    search_space: dict[str, list[Any]] | None = None,
    registry: TrialRegistry | None = None,
    allow_unknown_strategy: bool = False,
) -> StrategyProposal:
    """Reject invalid / duplicate / code / holdout proposals — never repair."""
    if isinstance(proposal, dict):
        raw_text = json.dumps(proposal)
        if proposal_contains_code(raw_text):
            raise AgentError("proposal containing code is rejected")
        if proposal_requests_holdout(raw_text):
            raise AgentError("proposal requesting holdout is rejected")
        try:
            prop = StrategyProposal.model_validate(proposal)
        except Exception as exc:
            raise AgentError(f"invalid schema proposal rejected: {exc}") from exc
    else:
        raw_text = proposal.model_dump_json()
        if proposal_contains_code(raw_text):
            raise AgentError("proposal containing code is rejected")
        if proposal_requests_holdout(raw_text):
            raise AgentError("proposal requesting holdout is rejected")
        prop = proposal

    if not allow_unknown_strategy:
        try:
            get_strategy(prop.strategy)
        except Exception as exc:
            raise AgentError(f"unknown strategy {prop.strategy!r}: {exc}") from exc

    if search_space:
        for key, allowed in search_space.items():
            if key not in prop.params:
                continue
            if prop.params[key] not in allowed:
                raise AgentError(
                    f"param {key}={prop.params[key]!r} not in search space {allowed!r}"
                )

    # Reject params that look like executable payloads
    for k, v in prop.params.items():
        if isinstance(v, str) and proposal_contains_code(v):
            raise AgentError(f"proposal param {k!r} contains code")
        if callable(v):
            raise AgentError(f"proposal param {k!r} is callable")

    registry = registry or default_registry()
    ch = config_hash(prop.strategy, prop.params)
    if registry.has_config(ch):
        raise AgentError(f"duplicate config rejected against registry: {ch}")

    return prop


def parse_proposals_from_llm_text(text: str) -> list[dict[str, Any]]:
    """Best-effort JSON array/object parse from LLM output."""
    text = text.strip()
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict):
            if "proposals" in data and isinstance(data["proposals"], list):
                return [x for x in data["proposals"] if isinstance(x, dict)]
            return [data]
    except json.JSONDecodeError:
        pass
    # Find first JSON array
    m = re.search(r"\[[\s\S]*\]", text)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, list):
                return [x for x in data if isinstance(x, dict)]
        except json.JSONDecodeError:
            pass
    return []
