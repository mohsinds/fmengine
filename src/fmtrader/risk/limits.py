"""Limits service and independent kill-switch — between signal and execution."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from fmtrader.core.errors import RiskError
from fmtrader.system.logging import get_logger

log = get_logger(__name__)

HaltReason = Literal[
    "ok",
    "kill_switch",
    "max_per_trade_loss",
    "max_daily_loss",
    "max_drawdown",
    "max_position",
    "max_trades_day",
    "consecutive_losses",
]


@dataclass
class LimitsConfig:
    max_per_trade_loss: float = 500.0  # absolute PnL units
    max_daily_loss: float = 2000.0
    max_drawdown_pct: float = 0.10  # from peak equity
    max_position: float = 5.0  # absolute size units
    max_trades_per_day: int = 50
    consecutive_loss_limit: int = 5


@dataclass
class AccountSnapshot:
    equity: float
    peak_equity: float
    position: float = 0.0
    daily_pnl: float = 0.0
    trades_today: int = 0
    consecutive_losses: int = 0
    day: str = field(default_factory=lambda: date.today().isoformat())


@dataclass(frozen=True)
class LimitsDecision:
    allow: bool
    reason: HaltReason
    detail: str = ""


class KillSwitch:
    """Independent kill-switch — file-backed so it works outside the strategy process."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path("data/risk/kill_switch.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def is_active(self) -> bool:
        if not self.path.exists():
            return False
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return bool(data.get("active", False))
        except (OSError, json.JSONDecodeError):
            return False

    def engage(self, *, reason: str, engaged_by: str = "operator") -> None:
        payload = {
            "active": True,
            "reason": reason,
            "engaged_by": engaged_by,
            "engaged_at": datetime.now(tz=UTC).isoformat(),
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        log.warning("kill_switch_engaged", reason=reason, engaged_by=engaged_by)

    def clear(self, *, cleared_by: str = "operator") -> None:
        payload = {
            "active": False,
            "cleared_by": cleared_by,
            "cleared_at": datetime.now(tz=UTC).isoformat(),
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        log.info("kill_switch_cleared", cleared_by=cleared_by)

    def status(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"active": False}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        return data


class LimitsService:
    """Evaluate account/trade limits. Never lives inside strategy code."""

    def __init__(
        self,
        config: LimitsConfig | None = None,
        kill_switch: KillSwitch | None = None,
    ) -> None:
        self.config = config or LimitsConfig()
        self.kill_switch = kill_switch or KillSwitch()

    def evaluate(
        self,
        *,
        account: AccountSnapshot,
        proposed_size: float,
        proposed_risk: float,
    ) -> LimitsDecision:
        if self.kill_switch.is_active():
            return LimitsDecision(False, "kill_switch", "kill-switch active")

        cfg = self.config
        if abs(proposed_risk) > cfg.max_per_trade_loss:
            return LimitsDecision(
                False,
                "max_per_trade_loss",
                f"proposed_risk={proposed_risk} > {cfg.max_per_trade_loss}",
            )
        if account.daily_pnl <= -abs(cfg.max_daily_loss):
            return LimitsDecision(
                False,
                "max_daily_loss",
                f"daily_pnl={account.daily_pnl} breached -{cfg.max_daily_loss}",
            )
        if account.peak_equity > 0:
            dd = 1.0 - (account.equity / account.peak_equity)
            if dd >= cfg.max_drawdown_pct:
                return LimitsDecision(
                    False,
                    "max_drawdown",
                    f"drawdown={dd:.3%} >= {cfg.max_drawdown_pct:.3%}",
                )
        if abs(proposed_size) > cfg.max_position:
            return LimitsDecision(
                False,
                "max_position",
                f"size={proposed_size} > max_position={cfg.max_position}",
            )
        if account.trades_today >= cfg.max_trades_per_day:
            return LimitsDecision(
                False,
                "max_trades_day",
                f"trades_today={account.trades_today} >= {cfg.max_trades_per_day}",
            )
        if account.consecutive_losses >= cfg.consecutive_loss_limit:
            return LimitsDecision(
                False,
                "consecutive_losses",
                f"consecutive_losses={account.consecutive_losses}",
            )
        return LimitsDecision(True, "ok")

    def record_trade_result(self, account: AccountSnapshot, pnl: float) -> AccountSnapshot:
        """Update consecutive-loss / daily counters after a fill (not strategy-owned)."""
        today = date.today().isoformat()
        if account.day != today:
            account = AccountSnapshot(
                equity=account.equity,
                peak_equity=account.peak_equity,
                position=account.position,
                daily_pnl=0.0,
                trades_today=0,
                consecutive_losses=account.consecutive_losses,
                day=today,
            )
        account.daily_pnl += pnl
        account.trades_today += 1
        account.equity += pnl
        account.peak_equity = max(account.peak_equity, account.equity)
        if pnl < 0:
            account.consecutive_losses += 1
        else:
            account.consecutive_losses = 0
        return account


def assert_limits_between_signal_and_execution() -> None:
    """Architectural assertion used by tests."""
    import fmtrader.strategy as strategy_pkg

    # Strategy package must not import risk.limits / risk.sizing for gating
    strat_file = Path(strategy_pkg.__file__ or "").parent
    offenders: list[str] = []
    for py in strat_file.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        if "fmtrader.risk.limits" in text or "from fmtrader.risk" in text:
            offenders.append(str(py))
    if offenders:
        raise RiskError(f"strategy code imports risk layer: {offenders}")
