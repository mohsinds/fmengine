"""Per-purpose LLM routing config (Ollama / OpenAI / Anthropic)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ProviderName = Literal["ollama", "openai", "anthropic", "stub"]
PurposeName = Literal[
    "hypothesize",
    "critique",
    "select",
    "report",
    "mutate",
    "summarize",
]


class LayerRoute(BaseModel):
    """Provider + model for one workflow purpose."""

    provider: ProviderName = "ollama"
    model: str = "qwen2.5-coder:7b"


def default_local_routing() -> dict[str, LayerRoute]:
    """All-local defaults — $0 API spend; 14B for critique/select when memory allows."""
    seven = LayerRoute(provider="ollama", model="qwen2.5-coder:7b")
    fourteen = LayerRoute(provider="ollama", model="qwen2.5:14b-instruct-q4_K_M")
    return {
        "hypothesize": seven,
        "critique": fourteen,
        "select": fourteen,
        "report": seven,
        "mutate": seven,
        "summarize": seven,
    }


class LLMRoutingConfig(BaseModel):
    """Map each agent purpose to a concrete provider/model."""

    hypothesize: LayerRoute = Field(
        default_factory=lambda: LayerRoute(provider="ollama", model="qwen2.5-coder:7b")
    )
    critique: LayerRoute = Field(
        default_factory=lambda: LayerRoute(
            provider="ollama", model="qwen2.5:14b-instruct-q4_K_M"
        )
    )
    select: LayerRoute = Field(
        default_factory=lambda: LayerRoute(
            provider="ollama", model="qwen2.5:14b-instruct-q4_K_M"
        )
    )
    report: LayerRoute = Field(
        default_factory=lambda: LayerRoute(provider="ollama", model="qwen2.5-coder:7b")
    )
    mutate: LayerRoute = Field(
        default_factory=lambda: LayerRoute(provider="ollama", model="qwen2.5-coder:7b")
    )
    summarize: LayerRoute = Field(
        default_factory=lambda: LayerRoute(provider="ollama", model="qwen2.5-coder:7b")
    )

    def for_purpose(self, purpose: str) -> LayerRoute:
        route = getattr(self, purpose, None)
        if isinstance(route, LayerRoute):
            return route
        return LayerRoute(provider="ollama", model="qwen2.5-coder:7b")

    def as_map(self) -> dict[str, LayerRoute]:
        return {
            "hypothesize": self.hypothesize,
            "critique": self.critique,
            "select": self.select,
            "report": self.report,
            "mutate": self.mutate,
            "summarize": self.summarize,
        }

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> LLMRoutingConfig:
        if not data:
            return cls()
        kwargs: dict[str, Any] = {}
        for key in (
            "hypothesize",
            "critique",
            "select",
            "report",
            "mutate",
            "summarize",
        ):
            raw = data.get(key)
            if isinstance(raw, dict):
                kwargs[key] = LayerRoute.model_validate(raw)
        return cls(**kwargs)
