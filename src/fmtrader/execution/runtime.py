"""Shared execution path for backtest replay and paper/live.

Strategies only emit positions via ``Strategy.generate``. This runtime converts
position deltas → risk → broker orders. Backtest and paper must call the same
``generate`` + delta logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import polars as pl

from fmtrader.execution.broker.base import BrokerAdapter, BrokerOrder, OrderReport
from fmtrader.execution.broker.client_ids import make_client_order_id
from fmtrader.execution.kill_bridge import KillSwitchBridge
from fmtrader.risk.limits import AccountSnapshot, KillSwitch
from fmtrader.risk.service import OrderIntent, RiskService, SignalIntent
from fmtrader.strategy.base import Strategy
from fmtrader.system.logging import get_logger

log = get_logger(__name__)

Mode = Literal["backtest", "paper", "live"]


@dataclass
class RuntimeConfig:
    symbol: str
    strategy_name: str
    params: dict[str, Any]
    mode: Mode = "paper"
    default_qty: float = 1.0


@dataclass
class BarAction:
    bar_index: int
    signal_key: str
    desired_position: int
    prior_position: int
    delta: int
    order: OrderReport | None = None
    risk_allow: bool = True
    reasons: tuple[str, ...] = ()


@dataclass
class RuntimeResult:
    actions: list[BarAction] = field(default_factory=list)
    desired_positions: list[int] = field(default_factory=list)
    fills: int = 0


def position_deltas(desired: np.ndarray) -> np.ndarray:
    """Target position change vs prior bar (first bar vs flat)."""
    out = np.zeros(len(desired), dtype=np.int64)
    prev = 0
    for i, d in enumerate(desired.astype(np.int64)):
        out[i] = int(d) - prev
        prev = int(d)
    return out


def signal_sequence_from_strategy(
    strategy: Strategy,
    bars: pl.DataFrame,
    params: dict[str, Any],
) -> np.ndarray:
    """Single code path: strategy.generate → int8 position array."""
    series = strategy.generate(bars, params)
    return series.to_numpy().astype(np.int8)


class ExecutionRuntime:
    """Drive strategy bars through risk → broker (paper/live) or dry record (backtest)."""

    def __init__(
        self,
        *,
        strategy: Strategy,
        config: RuntimeConfig,
        broker: BrokerAdapter | None = None,
        risk: RiskService | None = None,
        kill_switch: KillSwitch | None = None,
    ) -> None:
        self.strategy = strategy
        self.config = config
        self.broker = broker
        self.risk = risk or RiskService(kill_switch=kill_switch)
        self.kill = KillSwitchBridge(broker, kill_switch) if broker is not None else None

    def run(self, bars: pl.DataFrame) -> RuntimeResult:
        desired = signal_sequence_from_strategy(self.strategy, bars, self.config.params)
        deltas = position_deltas(desired)
        result = RuntimeResult(desired_positions=desired.astype(int).tolist())

        ts_col = bars["ts"] if "ts" in bars.columns else None
        close = bars["close"].to_numpy() if "close" in bars.columns else None

        if self.broker is not None and not self.broker.is_connected():
            self.broker.connect()
        if self.broker is not None:
            self.broker.subscribe(self.config.symbol)

        for i in range(len(desired)):
            if self.kill is not None:
                self.kill.poll()

            signal_key = str(ts_col[i]) if ts_col is not None else str(i)
            prior = int(desired[i - 1]) if i else 0
            target = int(desired[i])
            delta = int(deltas[i])
            action = BarAction(
                bar_index=i,
                signal_key=signal_key,
                desired_position=target,
                prior_position=prior,
                delta=delta,
            )

            if delta == 0:
                result.actions.append(action)
                continue

            side: Literal[-1, 0, 1] = 1 if delta > 0 else -1
            qty = abs(delta) * self.config.default_qty
            account = AccountSnapshot(equity=100_000.0, peak_equity=100_000.0)
            if self.broker is not None:
                acct = self.broker.account()
                account = AccountSnapshot(
                    equity=acct.equity, peak_equity=max(acct.equity, 100_000.0)
                )

            decision = self.risk.evaluate(
                SignalIntent(side=side),
                account=account,
            )
            action.risk_allow = decision.allow
            action.reasons = decision.reasons
            if not decision.allow or decision.order is None or not decision.order.allow:
                result.actions.append(action)
                continue

            order_intent: OrderIntent = decision.order
            fill_qty = abs(order_intent.size) if order_intent.size > 0 else qty
            if fill_qty <= 0:
                fill_qty = qty

            if self.config.mode == "backtest" or self.broker is None:
                # Dry-run: record intent only (fills happen in backtest engine)
                result.actions.append(action)
                continue

            assert self.broker is not None
            if close is not None:
                # Next-bar open fill model approximation: use this bar's close as mark
                # for paper; parity tests compare signal sequence, not fill prices.
                self.broker.set_mark_price(self.config.symbol, float(close[i]))

            coid = make_client_order_id(
                strategy=self.config.strategy_name,
                symbol=self.config.symbol,
                signal_key=signal_key,
                side=side,
                qty=fill_qty,
            )
            report = self.broker.submit(
                BrokerOrder(
                    client_order_id=coid,
                    symbol=self.config.symbol,
                    side=side,
                    qty=fill_qty,
                    strategy=self.config.strategy_name,
                )
            )
            action.order = report
            if report.status.value == "filled":
                result.fills += 1
            result.actions.append(action)

        return result
