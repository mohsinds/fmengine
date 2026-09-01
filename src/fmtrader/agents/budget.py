"""Budget governor — pre-call estimation, three-level caps, graceful degradation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from fmtrader.agents.ledger import CostLedger, LedgerEntry
from fmtrader.core.errors import BudgetError
from fmtrader.system.logging import get_logger

log = get_logger(__name__)

Tier = Literal["L", "F"]


@dataclass(frozen=True)
class BudgetCaps:
    per_campaign_usd: float = 0.0
    per_day_usd: float = 0.0
    per_generation_usd: float = 0.0


@dataclass(frozen=True)
class CallEstimate:
    provider: str
    model: str
    tier: Tier
    purpose: str
    estimated_prompt_tokens: int
    estimated_completion_tokens: int
    estimated_cost_usd: float


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    tier: Tier
    degraded: bool
    reason: str
    estimate: CallEstimate


# Rough USD per 1M tokens (order-of-magnitude; configurable later)
_COST_PER_MTOK: dict[str, tuple[float, float]] = {
    # (prompt, completion)
    "ollama": (0.0, 0.0),
    "anthropic": (3.0, 15.0),
    "openai": (2.5, 10.0),
    "gemini": (1.25, 5.0),
    "stub": (0.0, 0.0),
}


def estimate_cost_usd(
    *,
    provider: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    rates = _COST_PER_MTOK.get(provider, (5.0, 15.0))
    return (prompt_tokens / 1_000_000.0) * rates[0] + (completion_tokens / 1_000_000.0) * rates[1]


class BudgetGovernor:
    """Refuse calls that would breach caps; degrade Tier F → L on exhaustion."""

    def __init__(
        self,
        caps: BudgetCaps,
        ledger: CostLedger | None = None,
        *,
        allow_degrade_to_local: bool = True,
    ) -> None:
        self.caps = caps
        self.ledger = ledger or CostLedger()
        self.allow_degrade_to_local = allow_degrade_to_local

    def authorize(
        self,
        estimate: CallEstimate,
        *,
        campaign_id: str,
        generation: int,
    ) -> BudgetDecision:
        """Pre-call check. Never records a successful spend here — only refusals."""
        cost = estimate.estimated_cost_usd
        reasons: list[str] = []

        if self.caps.per_campaign_usd > 0:
            spent = self.ledger.spent_campaign(campaign_id)
            if spent + cost > self.caps.per_campaign_usd:
                reasons.append(
                    f"campaign cap ${self.caps.per_campaign_usd:.4f} "
                    f"(spent ${spent:.4f} + est ${cost:.4f})"
                )
        if self.caps.per_day_usd > 0:
            spent_d = self.ledger.spent_day()
            if spent_d + cost > self.caps.per_day_usd:
                reasons.append(
                    f"daily cap ${self.caps.per_day_usd:.4f} "
                    f"(spent ${spent_d:.4f} + est ${cost:.4f})"
                )
        if self.caps.per_generation_usd > 0:
            spent_g = self.ledger.spent_generation(campaign_id, generation)
            if spent_g + cost > self.caps.per_generation_usd:
                reasons.append(
                    f"generation cap ${self.caps.per_generation_usd:.4f} "
                    f"(spent ${spent_g:.4f} + est ${cost:.4f})"
                )

        if not reasons:
            return BudgetDecision(
                allowed=True, tier=estimate.tier, degraded=False, reason="ok", estimate=estimate
            )

        reason = "; ".join(reasons)
        # Attempt degrade F → L (free)
        if estimate.tier == "F" and self.allow_degrade_to_local:
            local = CallEstimate(
                provider="ollama",
                model="local-fallback",
                tier="L",
                purpose=estimate.purpose,
                estimated_prompt_tokens=estimate.estimated_prompt_tokens,
                estimated_completion_tokens=estimate.estimated_completion_tokens,
                estimated_cost_usd=0.0,
            )
            self._record_refusal(estimate, campaign_id, generation, reason)
            log.warning("budget_degrade_to_local", reason=reason, purpose=estimate.purpose)
            return BudgetDecision(
                allowed=True,
                tier="L",
                degraded=True,
                reason=f"degraded to local: {reason}",
                estimate=local,
            )

        self._record_refusal(estimate, campaign_id, generation, reason)
        log.warning("budget_refused", reason=reason, purpose=estimate.purpose)
        return BudgetDecision(
            allowed=False, tier=estimate.tier, degraded=False, reason=reason, estimate=estimate
        )

    def require(self, decision: BudgetDecision) -> BudgetDecision:
        if not decision.allowed:
            raise BudgetError(f"LLM call refused: {decision.reason}")
        return decision

    def record_success(
        self,
        *,
        campaign_id: str,
        generation: int,
        provider: str,
        model: str,
        tier: Tier,
        purpose: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float | None = None,
    ) -> int:
        cost = (
            cost_usd
            if cost_usd is not None
            else estimate_cost_usd(
                provider=provider,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
        )
        return self.ledger.record(
            LedgerEntry(
                campaign_id=campaign_id,
                generation=generation,
                provider=provider,
                model=model,
                tier=tier,
                purpose=purpose,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=cost,
                refused=False,
                refuse_reason=None,
                created_at=datetime.now(tz=UTC).isoformat(),
            )
        )

    def _record_refusal(
        self,
        estimate: CallEstimate,
        campaign_id: str,
        generation: int,
        reason: str,
    ) -> None:
        self.ledger.record(
            LedgerEntry(
                campaign_id=campaign_id,
                generation=generation,
                provider=estimate.provider,
                model=estimate.model,
                tier=estimate.tier,
                purpose=estimate.purpose,
                prompt_tokens=estimate.estimated_prompt_tokens,
                completion_tokens=estimate.estimated_completion_tokens,
                cost_usd=0.0,
                refused=True,
                refuse_reason=reason,
                created_at=datetime.now(tz=UTC).isoformat(),
            )
        )
