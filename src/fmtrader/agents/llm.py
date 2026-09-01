"""LLM router — tier selection, memory gate, local/frontier clients."""

from __future__ import annotations

from dataclasses import dataclass, field
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
    model: str = "qwen2.5-coder:7b"
    base_url: str = "http://localhost:11434"

    def complete(self, prompt: str, *, max_tokens: int = 1024) -> tuple[str, int, int]:
        try:
            import httpx
        except ImportError as exc:
            raise AgentError("httpx required for Ollama client") from exc
        try:
            r = httpx.post(
                f"{self.base_url.rstrip('/')}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_predict": max_tokens},
                },
                timeout=180.0,
            )
            r.raise_for_status()
            data = r.json()
            text = str(data.get("response") or "")
            pt = int(data.get("prompt_eval_count") or max(1, len(prompt) // 4))
            ct = int(data.get("eval_count") or max(1, len(text) // 4))
            return text, pt, ct
        except Exception as exc:
            log.warning("ollama_call_failed", error=str(exc), model=self.model)
            raise AgentError(f"Ollama call failed: {exc}") from exc


@dataclass
class OpenAILLMClient:
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"

    def complete(self, prompt: str, *, max_tokens: int = 1024) -> tuple[str, int, int]:
        if not self.api_key:
            raise AgentError("OPENAI_API_KEY not configured")
        try:
            import httpx
        except ImportError as exc:
            raise AgentError("httpx required for OpenAI client") from exc
        try:
            r = httpx.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                },
                timeout=120.0,
            )
            r.raise_for_status()
            data = r.json()
            text = str(data["choices"][0]["message"]["content"] or "")
            usage = data.get("usage") or {}
            pt = int(usage.get("prompt_tokens") or max(1, len(prompt) // 4))
            ct = int(usage.get("completion_tokens") or max(1, len(text) // 4))
            return text, pt, ct
        except Exception as exc:
            log.warning("openai_call_failed", error=str(exc), model=self.model)
            raise AgentError(f"OpenAI call failed: {exc}") from exc


@dataclass
class AnthropicLLMClient:
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-5-20250929"
    api_key: str = ""
    base_url: str = "https://api.anthropic.com"

    def complete(self, prompt: str, *, max_tokens: int = 1024) -> tuple[str, int, int]:
        if not self.api_key:
            raise AgentError("ANTHROPIC_API_KEY not configured")
        try:
            import httpx
        except ImportError as exc:
            raise AgentError("httpx required for Anthropic client") from exc
        try:
            r = httpx.post(
                f"{self.base_url.rstrip('/')}/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": max_tokens,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=120.0,
            )
            r.raise_for_status()
            data = r.json()
            blocks = data.get("content") or []
            text = "".join(str(b.get("text") or "") for b in blocks if isinstance(b, dict))
            usage = data.get("usage") or {}
            pt = int(usage.get("input_tokens") or max(1, len(prompt) // 4))
            ct = int(usage.get("output_tokens") or max(1, len(text) // 4))
            return text, pt, ct
        except Exception as exc:
            log.warning("anthropic_call_failed", error=str(exc), model=self.model)
            raise AgentError(f"Anthropic call failed: {exc}") from exc


@dataclass
class MultiFrontierClient:
    """Critical decisions: prefer Claude, then OpenAI, respecting provider soft caps."""

    anthropic: AnthropicLLMClient | None = None
    openai: OpenAILLMClient | None = None
    ledger: CostLedger | None = None
    campaign_id: str = ""
    anthropic_cap_usd: float = 5.0
    openai_cap_usd: float = 3.0
    provider: str = "anthropic"
    model: str = "multi-frontier"
    _purpose: str = field(default="critique", repr=False)

    def for_purpose(self, purpose: str) -> MultiFrontierClient:
        return MultiFrontierClient(
            anthropic=self.anthropic,
            openai=self.openai,
            ledger=self.ledger,
            campaign_id=self.campaign_id,
            anthropic_cap_usd=self.anthropic_cap_usd,
            openai_cap_usd=self.openai_cap_usd,
            _purpose=purpose,
        )

    def _pick(self) -> LLMClient:
        ledger = self.ledger or CostLedger()
        spent_a = ledger.spent_provider("anthropic", campaign_id=self.campaign_id or None)
        spent_o = ledger.spent_provider("openai", campaign_id=self.campaign_id or None)
        # critique/select → Claude first; report → OpenAI first (cheaper summarization)
        order: list[tuple[str, LLMClient | None, float, float]]
        if self._purpose == "report":
            order = [
                ("openai", self.openai, spent_o, self.openai_cap_usd),
                ("anthropic", self.anthropic, spent_a, self.anthropic_cap_usd),
            ]
        else:
            order = [
                ("anthropic", self.anthropic, spent_a, self.anthropic_cap_usd),
                ("openai", self.openai, spent_o, self.openai_cap_usd),
            ]
        for name, client, spent, cap in order:
            if client is None:
                continue
            if cap > 0 and spent >= cap:
                log.info("frontier_provider_cap_exhausted", provider=name, spent=spent, cap=cap)
                continue
            self.provider = client.provider
            self.model = client.model
            return client
        raise AgentError("No frontier provider available under OpenAI/Claude budgets")

    def complete(self, prompt: str, *, max_tokens: int = 1024) -> tuple[str, int, int]:
        ledger = self.ledger or CostLedger()
        spent_a = ledger.spent_provider("anthropic", campaign_id=self.campaign_id or None)
        spent_o = ledger.spent_provider("openai", campaign_id=self.campaign_id or None)
        if self._purpose == "report":
            order = [
                ("openai", self.openai, spent_o, self.openai_cap_usd),
                ("anthropic", self.anthropic, spent_a, self.anthropic_cap_usd),
            ]
        else:
            order = [
                ("anthropic", self.anthropic, spent_a, self.anthropic_cap_usd),
                ("openai", self.openai, spent_o, self.openai_cap_usd),
            ]
        errors: list[str] = []
        for name, client, spent, cap in order:
            if client is None:
                continue
            if cap > 0 and spent >= cap:
                log.info("frontier_provider_cap_exhausted", provider=name, spent=spent, cap=cap)
                continue
            try:
                self.provider = client.provider
                self.model = client.model
                return client.complete(prompt, max_tokens=max_tokens)
            except Exception as exc:
                errors.append(f"{name}: {exc}")
                log.warning("frontier_provider_failed", provider=name, error=str(exc))
        raise AgentError(
            "No frontier provider available under OpenAI/Claude budgets: "
            + ("; ".join(errors) if errors else "none configured")
        )


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
            client = self.frontier
            if isinstance(client, MultiFrontierClient):
                client = client.for_purpose(purpose)
                client.campaign_id = campaign_id
                # Estimate against preferred provider under cap (for authorize only)
                try:
                    preferred = client._pick()
                    provider, model = preferred.provider, preferred.model
                except AgentError:
                    provider, model = "anthropic", "frontier"
            else:
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
        if isinstance(client, MultiFrontierClient):
            provider, model = client.provider, client.model
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
    campaign_id: str = "",
    sweep_active: bool = True,
) -> LLMRouter:
    """Build router. Non-stub: Ollama for hypothesize; Claude/OpenAI for critical gating."""
    ledger = ledger or CostLedger()
    gov = BudgetGovernor(caps or BudgetCaps(), ledger=ledger)
    if stub:
        return LLMRouter(gov)
    from fmtrader.config.settings import get_settings

    settings = get_settings()
    local = OllamaLLMClient(model="qwen2.5-coder:7b", base_url=settings.ollama_url)
    local_14b = OllamaLLMClient(
        model="qwen2.5:14b-instruct-q4_K_M", base_url=settings.ollama_url
    )
    anthropic = (
        AnthropicLLMClient(api_key=settings.anthropic_api_key)
        if settings.anthropic_api_key
        else None
    )
    openai = (
        OpenAILLMClient(api_key=settings.openai_api_key) if settings.openai_api_key else None
    )
    if anthropic is None and openai is None:
        frontier: LLMClient = StubLLMClient(
            provider="stub", model="frontier-missing-keys", response='{"critique":"no frontier keys"}'
        )
    else:
        c = caps or BudgetCaps()
        frontier = MultiFrontierClient(
            anthropic=anthropic,
            openai=openai,
            ledger=ledger,
            campaign_id=campaign_id,
            anthropic_cap_usd=c.anthropic_usd or 5.0,
            openai_cap_usd=c.openai_usd or 3.0,
        )
    return LLMRouter(
        gov,
        local=local,
        local_14b=local_14b,
        frontier=frontier,
        sweep_active=sweep_active,
    )
