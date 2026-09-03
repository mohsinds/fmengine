"""Per-purpose LLM routing config (Ollama / Ollama Cloud / OpenAI / Anthropic)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ProviderName = Literal["ollama", "ollama_cloud", "openai", "anthropic", "stub"]
PurposeName = Literal[
    "hypothesize",
    "critique",
    "select",
    "report",
    "mutate",
    "summarize",
]

# Models that should not coexist in VRAM — unload between calls.
HEAVY_OLLAMA_MARKERS = ("14b", "20b", "27b", "30b", "32b", "70b", "qwen3.8", "gpt-oss")


class LayerRoute(BaseModel):
    """Provider + model for one workflow purpose."""

    provider: ProviderName = "ollama"
    model: str = "qwen2.5-coder:7b"
    fallback: LayerRoute | None = None
    """Optional fallback when primary (e.g. ollama_cloud) fails."""


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
                kwargs[key] = _parse_layer_route(raw)
        return cls(**kwargs)


def _parse_layer_route(raw: dict[str, Any]) -> LayerRoute:
    fb = raw.get("fallback")
    route_data = {k: v for k, v in raw.items() if k != "fallback"}
    route = LayerRoute.model_validate(route_data)
    if isinstance(fb, dict):
        route = route.model_copy(update={"fallback": _parse_layer_route(fb)})
    return route


def default_local_routing() -> dict[str, LayerRoute]:
    """Compact local defaults (7B / 14B)."""
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


def large_agent_routing() -> LLMRoutingConfig:
    """Research profile: gpt-oss:20b / kimi-k2.6:cloud / qwen3.8:27b."""
    qwen27 = LayerRoute(provider="ollama", model="qwen3.8:27b")
    gpt_oss = LayerRoute(provider="ollama", model="gpt-oss:20b")
    kimi = LayerRoute(
        provider="ollama_cloud",
        model="kimi-k2.6:cloud",
        fallback=qwen27,
    )
    return LLMRoutingConfig(
        hypothesize=gpt_oss,
        critique=kimi,
        select=LayerRoute(
            provider="ollama_cloud",
            model="kimi-k2.6:cloud",
            fallback=qwen27,
        ),
        report=qwen27,
        mutate=gpt_oss,
        summarize=LayerRoute(provider="ollama", model="qwen2.5-coder:7b"),
    )


def is_heavy_ollama_model(model: str) -> bool:
    m = model.lower()
    return any(x in m for x in HEAVY_OLLAMA_MARKERS)


LayerRoute.model_rebuild()
