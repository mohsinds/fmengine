"""Kill-switch bridge — cancels open broker orders independently of strategy."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from fmtrader.execution.broker.base import BrokerAdapter
from fmtrader.risk.limits import KillSwitch
from fmtrader.system.logging import get_logger

log = get_logger(__name__)

# Bound for cancel-all after kill engage (paper/sim: immediate; live SLA target)
DEFAULT_CANCEL_BOUND_MS = 500.0


@dataclass(frozen=True)
class KillSwitchAction:
    engaged: bool
    cancelled: int
    elapsed_ms: float
    within_bound: bool
    bound_ms: float


class KillSwitchBridge:
    """Poll file-backed kill-switch and cancel open orders on the broker."""

    def __init__(
        self,
        broker: BrokerAdapter,
        kill_switch: KillSwitch | None = None,
        *,
        cancel_bound_ms: float = DEFAULT_CANCEL_BOUND_MS,
        path: Path | None = None,
    ) -> None:
        self.broker = broker
        self.kill_switch = kill_switch or KillSwitch(path=path)
        self.cancel_bound_ms = cancel_bound_ms
        self._last_active = False

    def poll(self) -> KillSwitchAction | None:
        """If kill just became active (or is active), cancel all open orders."""
        active = self.kill_switch.is_active()
        if not active:
            self._last_active = False
            return None
        t0 = time.perf_counter()
        cancelled = 0
        if self.broker.is_connected():
            reports = self.broker.cancel_all()
            cancelled = len(reports)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        action = KillSwitchAction(
            engaged=True,
            cancelled=cancelled,
            elapsed_ms=elapsed_ms,
            within_bound=elapsed_ms <= self.cancel_bound_ms,
            bound_ms=self.cancel_bound_ms,
        )
        if not self._last_active:
            log.warning(
                "kill_switch_cancel_all",
                cancelled=cancelled,
                elapsed_ms=elapsed_ms,
                within_bound=action.within_bound,
            )
        self._last_active = True
        return action
