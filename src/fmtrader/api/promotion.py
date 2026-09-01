"""Promotion gate — DSR failure blocks promotion; override is audit-logged."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fmtrader.backtest.validation.gates import evaluate_gates
from fmtrader.core.errors import ValidationError
from fmtrader.execution.recorder import ExecutionManifest


@dataclass(frozen=True)
class PromotionDecision:
    allowed: bool
    reason: str
    dsr: float
    min_dsr: float
    verdict: str
    override: bool = False


def _metrics_float(metrics: dict[str, Any], *keys: str, default: float = 0.0) -> float:
    for k in keys:
        if k in metrics and metrics[k] is not None:
            try:
                return float(metrics[k])
            except (TypeError, ValueError):
                continue
    return default


def promotion_decision(
    manifest: ExecutionManifest,
    *,
    min_dsr: float = 0.5,
    max_pbo: float = 0.5,
    override: bool = False,
    justification: str | None = None,
) -> PromotionDecision:
    """Evaluate whether an execution may be promoted.

    Failing DSR blocks promotion unless ``override`` with non-empty justification.
    """
    if not manifest.is_complete:
        return PromotionDecision(
            allowed=False,
            reason="manifest incomplete",
            dsr=0.0,
            min_dsr=min_dsr,
            verdict="INCOMPLETE",
        )
    if not manifest.promotable:
        return PromotionDecision(
            allowed=False,
            reason="execution marked fragile or incomplete",
            dsr=_metrics_float(manifest.metrics_net, "dsr", "deflated_sharpe"),
            min_dsr=min_dsr,
            verdict="FRAGILE",
        )

    net = manifest.metrics_net
    dsr = _metrics_float(net, "dsr", "deflated_sharpe")
    pbo = _metrics_float(net, "pbo", default=1.0)
    sharpe_1x = _metrics_float(net, "sharpe", "sharpe_net", "total_return_net")
    sens = manifest.cost_sensitivity or {}
    sens_15: dict[str, Any] = {}
    if isinstance(sens, dict):
        raw_15 = sens.get("1.5", sens.get("1.5x", {}))
        if isinstance(raw_15, dict):
            sens_15 = raw_15
    sharpe_15 = _metrics_float(
        sens_15,
        "sharpe",
        "sharpe_net",
        default=sharpe_1x,
    )
    if isinstance(sens, dict) and "1.5" not in sens and "1.5x" not in sens:
        # Flat map of multipliers
        for k, v in sens.items():
            if str(k).startswith("1.5") and isinstance(v, dict):
                sharpe_15 = _metrics_float(v, "sharpe", "sharpe_net", default=sharpe_15)
                break

    gate = evaluate_gates(
        dsr=dsr,
        pbo=pbo,
        net_sharpe_1x=sharpe_1x,
        net_sharpe_15x=sharpe_15,
        cost_drag_pct=float(manifest.cost_drag_pct or 0.0),
        trade_count=int(manifest.trade_count),
        holdout_consumed=bool(net.get("holdout_consumed", False)),
        holdout_passed=bool(net.get("holdout_passed", False)),
        min_dsr=min_dsr,
        max_pbo=max_pbo,
    )

    if gate.verdict in ("CANDIDATE", "VALIDATED"):
        return PromotionDecision(
            allowed=True,
            reason="gates passed",
            dsr=dsr,
            min_dsr=min_dsr,
            verdict=gate.verdict,
        )

    if gate.verdict == "NOISE" or dsr < min_dsr:
        if override:
            if not justification or not justification.strip():
                raise ValidationError("Override requires written justification")
            return PromotionDecision(
                allowed=True,
                reason=f"override: {justification.strip()}",
                dsr=dsr,
                min_dsr=min_dsr,
                verdict=gate.verdict,
                override=True,
            )
        return PromotionDecision(
            allowed=False,
            reason=f"DSR gate failed: DSR={dsr:.3f} < {min_dsr} (verdict={gate.verdict})",
            dsr=dsr,
            min_dsr=min_dsr,
            verdict=gate.verdict,
        )

    return PromotionDecision(
        allowed=False,
        reason="; ".join(gate.reasons) or f"verdict={gate.verdict}",
        dsr=dsr,
        min_dsr=min_dsr,
        verdict=gate.verdict,
    )


def audit_promotion(
    *,
    audit_path: Path,
    execution_id: str,
    decision: PromotionDecision,
    actor: str = "api",
) -> None:
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "at": datetime.now(tz=UTC).isoformat(),
        "execution_id": execution_id,
        "allowed": decision.allowed,
        "reason": decision.reason,
        "dsr": decision.dsr,
        "verdict": decision.verdict,
        "override": decision.override,
        "actor": actor,
    }
    with audit_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
