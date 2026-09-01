"""Limits and kill-switch unit tests."""

from __future__ import annotations

from pathlib import Path

from fmtrader.risk.limits import (
    AccountSnapshot,
    KillSwitch,
    LimitsConfig,
    LimitsService,
    assert_limits_between_signal_and_execution,
)
from fmtrader.risk.service import RiskService, SignalIntent


def _acct(**kwargs: float | int | str) -> AccountSnapshot:
    base = AccountSnapshot(equity=100_000.0, peak_equity=100_000.0)
    for k, v in kwargs.items():
        setattr(base, k, v)
    return base


def test_daily_loss_limit_halts_trading(tmp_path: Path) -> None:
    svc = LimitsService(LimitsConfig(max_daily_loss=1000.0), KillSwitch(tmp_path / "ks.json"))
    d = svc.evaluate(account=_acct(daily_pnl=-1500.0), proposed_size=1.0, proposed_risk=10.0)
    assert d.allow is False
    assert d.reason == "max_daily_loss"


def test_drawdown_limit_halts_trading(tmp_path: Path) -> None:
    svc = LimitsService(LimitsConfig(max_drawdown_pct=0.10), KillSwitch(tmp_path / "ks.json"))
    d = svc.evaluate(
        account=_acct(equity=85_000.0, peak_equity=100_000.0),
        proposed_size=1.0,
        proposed_risk=10.0,
    )
    assert d.allow is False
    assert d.reason == "max_drawdown"


def test_consecutive_loss_breaker_fires(tmp_path: Path) -> None:
    svc = LimitsService(LimitsConfig(consecutive_loss_limit=3), KillSwitch(tmp_path / "ks.json"))
    d = svc.evaluate(
        account=_acct(consecutive_losses=3),
        proposed_size=1.0,
        proposed_risk=10.0,
    )
    assert d.allow is False
    assert d.reason == "consecutive_losses"


def test_kill_switch_blocks_all_orders(tmp_path: Path) -> None:
    ks = KillSwitch(tmp_path / "ks.json")
    ks.engage(reason="test halt")
    svc = LimitsService(kill_switch=ks)
    d = svc.evaluate(account=_acct(), proposed_size=0.1, proposed_risk=1.0)
    assert d.allow is False
    assert d.reason == "kill_switch"
    # Via RiskService path too
    risk = RiskService(limits=svc, kill_switch=ks)
    decision = risk.evaluate(
        SignalIntent(side=1, probability=0.7, calibrated=True),
        account=_acct(),
    )
    assert decision.allow is False
    assert "kill_switch" in decision.reasons


def test_limits_evaluated_between_signal_and_execution() -> None:
    assert_limits_between_signal_and_execution()
    # RiskService is the choke point: strategy emits SignalIntent only
    import fmtrader.risk.service as svc_mod

    src = Path(svc_mod.__file__).read_text(encoding="utf-8")
    assert "SignalIntent" in src
    assert "OrderIntent" in src
    assert "limits.evaluate" in src or "self.limits.evaluate" in src
