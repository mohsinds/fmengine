"""Conformal uncertainty gate — skip/shrink when prediction set is too wide."""

from __future__ import annotations

from dataclasses import dataclass

from fmtrader.core.errors import RiskError
from fmtrader.models.conformal import ConformalInterval, SplitConformalClassifier


@dataclass(frozen=True)
class ConformalGateConfig:
    max_width: float = 0.4
    # Even if point prob is high, reject when interval is wide
    reject_high_prob_if_wide: bool = True
    high_prob_threshold: float = 0.6


@dataclass(frozen=True)
class GateDecision:
    allow: bool
    reason: str
    interval: ConformalInterval | None = None
    size_scale: float = 1.0


class ConformalGate:
    """Gate signals through conformal interval width."""

    def __init__(
        self,
        model: SplitConformalClassifier,
        config: ConformalGateConfig | None = None,
    ) -> None:
        self.model = model
        self.config = config or ConformalGateConfig()
        if not model.fitted:
            raise RiskError("ConformalGate requires a fitted conformal model")

    def evaluate(self, probability: float) -> GateDecision:
        iv = self.model.predict_interval(probability)[0]
        cfg = self.config
        if iv.width > cfg.max_width:
            if cfg.reject_high_prob_if_wide or probability >= cfg.high_prob_threshold:
                return GateDecision(
                    allow=False,
                    reason=(
                        f"wide conformal interval width={iv.width:.3f} > {cfg.max_width} "
                        f"(p={probability:.3f} in [{iv.lower:.3f}, {iv.upper:.3f}])"
                    ),
                    interval=iv,
                    size_scale=0.0,
                )
            # Shrink rather than skip
            scale = max(0.0, 1.0 - (iv.width - cfg.max_width))
            return GateDecision(
                allow=True,
                reason=f"wide interval — size scaled to {scale:.2f}",
                interval=iv,
                size_scale=scale,
            )
        return GateDecision(allow=True, reason="ok", interval=iv, size_scale=1.0)
