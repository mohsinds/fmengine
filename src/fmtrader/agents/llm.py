"""LLM router — tier selection, memory gate, local/frontier clients."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from fmtrader.agents.budget import (
    BudgetCaps,
    BudgetGovernor,
    CallEstimate,
    Tier,
    estimate_cost_usd,
)
from fmtrader.agents.ledger import CostLedger
from fmtrader.core.errors import AgentError, BudgetError
from fmtrader.system.logging import get_logger
from fmtrader.system.memory import collect_memory_snapshot

log = get_logger(__name__)

Purpose = Literal[
    "hypothesize",
    "critique",
    "select",
    "report",
    "mutate",
    "summarize",
]

# Gating purposes that may use frontier (Tier F); everything else stays local.
_FRONTIER_PURPOSES: frozenset[str] = frozenset({"critique", "select", "report"})


class LLMClient(Protocol):
    provider: str
    model: str

    def complete(self, prompt: str, *, max_tokens: int = 1024) -> tuple[str, int, int]:
        """Return (text, prompt_tokens, completion_tokens)."""
        ...


@dataclass
class StubLLMClient:
    """Deterministic stub for tests — no network."""

    provider: str = "stub"
    model: str = "stub-l"
    response: str = "{}"

    def complete(self, prompt: str, *, max_tokens: int = 1024) -> tuple[str, int, int]:
        _ = max_tokens
        pt = max(1, len(prompt) // 4)
        ct = max(1, len(self.response) // 4)
        return self.response, pt, ct


@dataclass
class OllamaLLMClient:
    provider: str = "ollama"
    model: str = "llama3.2:3b"
    base_url: str = "http://localhost:11434"

    def complete(self, prompt: str, *, max_tokens: int = 1024) -> tuple[str, int, int]:
        try:
            import httpx
        except ImportError as exc:
            raise AgentError("httpx required for Ollama client") from exc
        try:
            r = httpx.post(
                f"{self.base_url.rstrip('/')}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": False},
                timeout=120.0,
            )
            r.raise_for_status()
            data = r.json()
            text = str(data.get("response") or "")
            pt = int(data.get("prompt_eval_count") or max(1, len(prompt) // 4))
            ct = int(data.get("eval_count") or max(1, len(text) // 4))
            return text, pt, ct
        except Exception as exc:
            log.warning("ollama_call_failed", error=str(exc))
            raise AgentError(f"Ollama call failed: {exc}") from exc


class LLMRouter:
    """Route by purpose + memory + budget; never loads 14B during an active sweep."""

    def __init__(
        self,
        governor: BudgetGovernor,
        *,
        local: LLMClient | None = None,
        frontier: LLMClient | None = None,
        local_14b: LLMClient | None = None,
        min_available_gb_for_14b: float = 10.0,
        sweep_active: bool = False,
    ) -> None:
        self.governor = governor
        self.local = local or StubLLMClient(provider="stub", model="stub-l", response="[]")
        self.frontier = frontier or StubLLMClient(
            provider="stub", model="stub-f", response='{"ok": true}'
        )
        self.local_14b = local_14b
        self.min_available_gb_for_14b = min_available_gb_for_14b
        self.sweep_active = sweep_active

    def select_tier(self, purpose: Purpose) -> Tier:
        if purpose in _FRONTIER_PURPOSES:
            return "F"
        return "L"

    def select_local_client(self) -> LLMClient:
        """Fall back to smaller local model when memory is tight or sweep is active."""
        if self.sweep_active:
            log.info("llm_skip_14b_during_sweep")
            return self.local
        if self.local_14b is None:
            return self.local
        snap = collect_memory_snapshot()
        if snap.available_gb < self.min_available_gb_for_14b:
            log.info(
                "llm_fallback_7b_low_memory",
                available_gb=snap.available_gb,
                threshold=self.min_available_gb_for_14b,
            )
            return self.local
        return self.local_14b

    def complete(
        self,
        prompt: str,
        *,
        purpose: Purpose,
        campaign_id: str,
        generation: int,
        max_tokens: int = 1024,
        estimated_prompt_tokens: int | None = None,
        estimated_completion_tokens: int | None = None,
    ) -> dict[str, Any]:
        tier = self.select_tier(purpose)
        if tier == "F":
            client: LLMClient = self.frontier
            provider, model = client.provider, client.model
        else:
            client = self.select_local_client()
            provider, model = client.provider, client.model

        pt_est = estimated_prompt_tokens or max(1, len(prompt) // 4)
        ct_est = estimated_completion_tokens or max_tokens
        estimate = CallEstimate(
            provider=provider,
            model=model,
            tier=tier,
            purpose=purpose,
            estimated_prompt_tokens=pt_est,
            estimated_completion_tokens=ct_est,
            estimated_cost_usd=estimate_cost_usd(
                provider=provider, prompt_tokens=pt_est, completion_tokens=ct_est
            ),
        )
        decision = self.governor.authorize(estimate, campaign_id=campaign_id, generation=generation)
        if not decision.allowed:
            raise BudgetError(f"LLM call refused: {decision.reason}")

        if decision.degraded:
            client = self.select_local_client()
            provider, model = client.provider, client.model
            tier = "L"

        text, pt, ct = client.complete(prompt, max_tokens=max_tokens)
        cost = estimate_cost_usd(provider=provider, prompt_tokens=pt, completion_tokens=ct)
        self.governor.record_success(
            campaign_id=campaign_id,
            generation=generation,
            provider=provider,
            model=model,
            tier=tier,
            purpose=purpose,
            prompt_tokens=pt,
            completion_tokens=ct,
            cost_usd=cost,
        )
        return {
            "text": text,
            "provider": provider,
            "model": model,
            "tier": tier,
            "degraded": decision.degraded,
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "cost_usd": cost,
            "purpose": purpose,
        }


def default_router(
    *,
    caps: BudgetCaps | None = None,
    ledger: CostLedger | None = None,
    stub: bool = True,
) -> LLMRouter:
    gov = BudgetGovernor(caps or BudgetCaps(), ledger=ledger)
    if stub:
        return LLMRouter(gov)
    from fmtrader.config.settings import get_settings

    settings = get_settings()
    local = OllamaLLMClient(base_url=settings.ollama_url)
    return LLMRouter(
        gov, local=local, frontier=StubLLMClient(provider="stub", model="frontier-stub")
    )
