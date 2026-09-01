"""Risk service — single choke point between signal and execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from fmtrader.core.errors import RiskError
from fmtrader.models.calibration import CalibratedProbability
from fmtrader.risk.conformal_gate import ConformalGate, GateDecision
from fmtrader.risk.limits import AccountSnapshot, KillSwitch, LimitsConfig, LimitsService
from fmtrader.risk.sizing import SizingConfig, apply_vol_targeting, fractional_kelly
from fmtrader.system.logging import get_logger

log = get_logger(__name__)

Side = Literal[-1, 0, 1]


@dataclass(frozen=True)
class SignalIntent:
    """Strategy output — desired side and optional model probability."""

    side: Side
    probability: float | None = None
    calibrated: bool = False
    stop_distance: float | None = None
    realized_vol: float | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class OrderIntent:
    """Risk-approved order for the execution layer."""

    side: Side
    size: float
    allow: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RiskDecision:
    allow: bool
    order: OrderIntent | None
    reasons: tuple[str, ...]
    gate: GateDecision | None = None
    size: float = 0.0


class RiskService:
    """Evaluate signal → size → limits → (optional) conformal gate.

    Strategies must never call brokers directly; they emit ``SignalIntent`` only.
    """

    def __init__(
        self,
        *,
        sizing: SizingConfig | None = None,
        limits: LimitsService | None = None,
        conformal_gate: ConformalGate | None = None,
        kill_switch: KillSwitch | None = None,
        odds_b: float = 1.0,
    ) -> None:
        self.sizing = sizing or SizingConfig()
        ks = kill_switch or KillSwitch()
        self.limits = limits or LimitsService(LimitsConfig(), kill_switch=ks)
        self.conformal_gate = conformal_gate
        self.odds_b = odds_b

    def evaluate(
        self,
        signal: SignalIntent,
        *,
        account: AccountSnapshot,
        calibrated_prob: CalibratedProbability | None = None,
    ) -> RiskDecision:
        reasons: list[str] = []

        # Independent kill-switch first
        if self.limits.kill_switch.is_active():
            return RiskDecision(
                allow=False,
                order=OrderIntent(side=0, size=0.0, allow=False, reasons=("kill_switch",)),
                reasons=("kill_switch",),
            )

        if signal.side == 0:
            return RiskDecision(
                allow=True,
                order=OrderIntent(side=0, size=0.0, allow=True, reasons=("flat",)),
                reasons=("flat",),
            )

        # Probability + calibration for Kelly
        p: float | None = None
        calibrated = False
        if calibrated_prob is not None:
            if calibrated_prob.values.size != 1:
                # Use last / mean for batch; for single-signal path expect size 1
                p = float(calibrated_prob.values.ravel()[-1])
            else:
                p = float(calibrated_prob.values[0])
            calibrated = True
        elif signal.probability is not None:
            p = float(signal.probability)
            calibrated = bool(signal.calibrated)

        gate_decision: GateDecision | None = None
        size_scale = 1.0
        if self.conformal_gate is not None and p is not None:
            gate_decision = self.conformal_gate.evaluate(p)
            if not gate_decision.allow:
                return RiskDecision(
                    allow=False,
                    order=OrderIntent(
                        side=0, size=0.0, allow=False, reasons=(gate_decision.reason,)
                    ),
                    reasons=(gate_decision.reason,),
                    gate=gate_decision,
                )
            size_scale = gate_decision.size_scale
            reasons.append(gate_decision.reason)

        # Sizing
        if p is None:
            # No probability — fixed fractional from config max_risk as notional fraction
            size = self.sizing.max_risk_per_trade * size_scale
            reasons.append("fixed_fractional_no_probability")
        else:
            try:
                size = fractional_kelly(
                    p,
                    b=self.odds_b,
                    fraction=self.sizing.kelly_fraction,
                    max_risk_per_trade=self.sizing.max_risk_per_trade,
                    calibrated=calibrated,
                )
            except RiskError as exc:
                return RiskDecision(
                    allow=False,
                    order=None,
                    reasons=(str(exc),),
                    gate=gate_decision,
                )
            size *= size_scale
            reasons.append("fractional_kelly")

        if signal.realized_vol is not None:
            size = apply_vol_targeting(
                size,
                signal.realized_vol,
                target_vol=self.sizing.target_vol,
            )
            reasons.append("vol_targeting")

        size = float(max(self.sizing.min_size, min(size, self.sizing.max_size)))
        signed = float(signal.side) * size

        # Limits between signal and execution
        proposed_risk = abs(signed) * (signal.stop_distance or account.equity * 0.01)
        lim = self.limits.evaluate(
            account=account,
            proposed_size=abs(signed),
            proposed_risk=proposed_risk,
        )
        if not lim.allow:
            return RiskDecision(
                allow=False,
                order=OrderIntent(side=0, size=0.0, allow=False, reasons=(lim.reason,)),
                reasons=(lim.detail or lim.reason,),
                gate=gate_decision,
                size=0.0,
            )

        order = OrderIntent(side=signal.side, size=abs(signed), allow=True, reasons=tuple(reasons))
        log.info(
            "risk_approved",
            side=signal.side,
            size=order.size,
            reasons=reasons,
        )
        return RiskDecision(
            allow=True, order=order, reasons=tuple(reasons), gate=gate_decision, size=order.size
        )
