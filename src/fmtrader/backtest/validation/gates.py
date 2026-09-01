"""Gate evaluator — NOISE / FRAGILE / CANDIDATE / VALIDATED."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

Verdict = Literal["NOISE", "FRAGILE", "CANDIDATE", "VALIDATED"]


@dataclass
class GateResult:
    verdict: Verdict
    reasons: list[str]
    dsr: float
    pbo: float
    net_sharpe_1x: float
    net_sharpe_15x: float
    cost_drag_pct: float
    trade_count: int
    holdout_consumed: bool
    regime_ok: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_gates(
    *,
    dsr: float,
    pbo: float,
    net_sharpe_1x: float,
    net_sharpe_15x: float,
    cost_drag_pct: float,
    trade_count: int,
    holdout_consumed: bool,
    holdout_passed: bool = False,
    regime_ok: bool = True,
    min_trades: int = 30,
    max_pbo: float = 0.5,
    min_dsr: float = 0.5,
) -> GateResult:
    """Assign a verdict from validation statistics.

    - NOISE: DSR weak or PBO high
    - FRAGILE: edge dies at 1.5x costs
    - CANDIDATE: passes research gates, holdout not yet consumed
    - VALIDATED: candidate gates + holdout consumed and passed
    """
    reasons: list[str] = []

    if dsr < min_dsr or pbo > max_pbo:
        if dsr < min_dsr:
            reasons.append(f"DSR={dsr:.3f} < {min_dsr}")
        if pbo > max_pbo:
            reasons.append(f"PBO={pbo:.3f} > {max_pbo}")
        return GateResult(
            verdict="NOISE",
            reasons=reasons,
            dsr=dsr,
            pbo=pbo,
            net_sharpe_1x=net_sharpe_1x,
            net_sharpe_15x=net_sharpe_15x,
            cost_drag_pct=cost_drag_pct,
            trade_count=trade_count,
            holdout_consumed=holdout_consumed,
            regime_ok=regime_ok,
        )

    if net_sharpe_1x > 0 and net_sharpe_15x <= 0:
        reasons.append("Edge dies at 1.5x costs")
        return GateResult(
            verdict="FRAGILE",
            reasons=reasons,
            dsr=dsr,
            pbo=pbo,
            net_sharpe_1x=net_sharpe_1x,
            net_sharpe_15x=net_sharpe_15x,
            cost_drag_pct=cost_drag_pct,
            trade_count=trade_count,
            holdout_consumed=holdout_consumed,
            regime_ok=regime_ok,
        )

    if trade_count < min_trades:
        reasons.append(f"Trade count {trade_count} < {min_trades}")
        return GateResult(
            verdict="NOISE",
            reasons=reasons,
            dsr=dsr,
            pbo=pbo,
            net_sharpe_1x=net_sharpe_1x,
            net_sharpe_15x=net_sharpe_15x,
            cost_drag_pct=cost_drag_pct,
            trade_count=trade_count,
            holdout_consumed=holdout_consumed,
            regime_ok=regime_ok,
        )

    if not regime_ok:
        reasons.append("Single-regime edge")
        # Still can be candidate but labeled — treat as fragile-ish noise for gates
        return GateResult(
            verdict="FRAGILE",
            reasons=reasons,
            dsr=dsr,
            pbo=pbo,
            net_sharpe_1x=net_sharpe_1x,
            net_sharpe_15x=net_sharpe_15x,
            cost_drag_pct=cost_drag_pct,
            trade_count=trade_count,
            holdout_consumed=holdout_consumed,
            regime_ok=regime_ok,
        )

    if holdout_consumed and holdout_passed:
        reasons.append("All gates passed; holdout consumed")
        return GateResult(
            verdict="VALIDATED",
            reasons=reasons,
            dsr=dsr,
            pbo=pbo,
            net_sharpe_1x=net_sharpe_1x,
            net_sharpe_15x=net_sharpe_15x,
            cost_drag_pct=cost_drag_pct,
            trade_count=trade_count,
            holdout_consumed=holdout_consumed,
            regime_ok=regime_ok,
        )

    if holdout_consumed and not holdout_passed:
        reasons.append("Holdout failed")
        return GateResult(
            verdict="NOISE",
            reasons=reasons,
            dsr=dsr,
            pbo=pbo,
            net_sharpe_1x=net_sharpe_1x,
            net_sharpe_15x=net_sharpe_15x,
            cost_drag_pct=cost_drag_pct,
            trade_count=trade_count,
            holdout_consumed=holdout_consumed,
            regime_ok=regime_ok,
        )

    reasons.append("Research gates passed; holdout not consumed")
    return GateResult(
        verdict="CANDIDATE",
        reasons=reasons,
        dsr=dsr,
        pbo=pbo,
        net_sharpe_1x=net_sharpe_1x,
        net_sharpe_15x=net_sharpe_15x,
        cost_drag_pct=cost_drag_pct,
        trade_count=trade_count,
        holdout_consumed=holdout_consumed,
        regime_ok=regime_ok,
    )
