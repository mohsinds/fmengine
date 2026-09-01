"""Shared next-bar fill engine used by both triage and fidelity lanes.

Invariant: a position change decided on bar ``i`` fills at bar ``i+1`` open
(cost-adjusted). Same-bar entry+exit and signal-bar close fills are rejected.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import polars as pl

from fmtrader.backtest.costs import CostModel
from fmtrader.backtest.enrichment import TradeRecord, compute_mae_mfe
from fmtrader.backtest.funnel import Funnel
from fmtrader.backtest.metrics import Metrics, compute_metrics
from fmtrader.core.errors import FeatureError


@dataclass
class BacktestResult:
    lane: str
    equity_net: np.ndarray
    equity_gross: np.ndarray
    position: np.ndarray
    trades: list[TradeRecord]
    metrics_net: Metrics
    metrics_gross: Metrics
    funnel: Funnel
    fill_prices: np.ndarray

    def to_summary(self) -> dict[str, Any]:
        return {
            "lane": self.lane,
            "metrics_net": self.metrics_net.to_dict(),
            "metrics_gross": self.metrics_gross.to_dict(),
            "cost_drag_pct": self.metrics_net.cost_drag_pct,
            "trade_count": self.metrics_net.trade_count,
            "total_return_net": self.metrics_net.total_return_net,
            "funnel": self.funnel.to_dict(),
        }


def run_next_bar_engine(
    bars: pl.DataFrame,
    desired_position: np.ndarray,
    cost: CostModel,
    *,
    lane: str,
    initial_cash: float = 100_000.0,
    qty: float = 1.0,
    fill_on: Literal["open", "close"] = "open",
    allow_signal_bar_fill: bool = False,
) -> BacktestResult:
    """Simulate fills at the next bar open (default)."""
    if allow_signal_bar_fill or fill_on == "close":
        raise FeatureError(
            "signal-bar close fills are rejected (look-ahead); use next-bar open fills"
        )
    n = bars.height
    if desired_position.shape[0] != n:
        raise FeatureError("position length must match bars")

    open_ = bars["open"].to_numpy().astype(np.float64)
    high = bars["high"].to_numpy().astype(np.float64)
    low = bars["low"].to_numpy().astype(np.float64)
    close = bars["close"].to_numpy().astype(np.float64)
    in_session = (
        bars["is_tradable"].to_numpy().astype(bool)
        if "is_tradable" in bars.columns
        else np.ones(n, dtype=bool)
    )

    tr = np.maximum(
        high - low,
        np.maximum(np.abs(high - np.roll(close, 1)), np.abs(low - np.roll(close, 1))),
    )
    tr[0] = high[0] - low[0]
    atr = np.copy(tr)
    for i in range(1, n):
        a = max(0, i - 13)
        atr[i] = float(np.mean(tr[a : i + 1]))

    desired = desired_position.astype(np.int8).copy()
    raw_changes = int(np.sum(np.diff(desired, prepend=desired[0] * 0) != 0))

    # Hold prior desired through non-tradable bars (no new entries)
    for i in range(n):
        if not in_session[i]:
            desired[i] = desired[i - 1] if i else 0
    after_regime = int(np.sum(np.diff(desired, prepend=0) != 0))

    # Next-bar fill: position[i] = desired[i-1]
    position = np.zeros(n, dtype=np.int8)
    position[1:] = desired[:-1]
    orders = int(np.sum(np.diff(position.astype(np.int16), prepend=0) != 0))

    funnel = Funnel()
    funnel.set_count("raw_signals", raw_changes)
    funnel.set_count("after_regime", after_regime)
    funnel.set_count("after_gate", after_regime)
    funnel.set_count("after_risk", after_regime)
    funnel.set_count("orders", orders)
    funnel.set_count("fills", orders)
    if raw_changes >= after_regime:
        funnel.add_drop("after_regime", "non_tradable", raw_changes - after_regime)
    if after_regime >= orders:
        funnel.add_drop("orders", "next_bar_shift", after_regime - orders)
    funnel.validate()

    cash_net = float(initial_cash)
    cash_gross = float(initial_cash)
    held = 0.0
    entry_i = -1
    entry_px_net = 0.0
    entry_px_gross = 0.0
    entry_side = 0
    entry_comm = 0.0
    trades: list[TradeRecord] = []
    equity_net = np.zeros(n)
    equity_gross = np.zeros(n)
    fill_prices = np.full(n, np.nan)

    def _close_trade(i: int, px_mid: float) -> None:
        nonlocal cash_net, cash_gross, held, entry_i, entry_comm
        if held == 0.0:
            return
        if entry_i == i:
            raise FeatureError("same-bar entry and exit is rejected")
        side_close: Literal["buy", "sell"] = "sell" if held > 0 else "buy"
        fill_px, fc = cost.one_way(
            price=px_mid,
            side=side_close,
            vol_proxy=float(atr[i]),
            in_session=bool(in_session[i]),
            size=abs(held),
        )
        fill_prices[i] = fill_px
        pnl_gross = (px_mid - entry_px_gross) * held
        pnl_net = (fill_px - entry_px_net) * held - entry_comm - fc.commission
        cash_net += fill_px * held - fc.commission
        cash_gross += px_mid * held
        mae, mfe = compute_mae_mfe(
            side=entry_side,
            entry_price=entry_px_gross,
            highs=high[entry_i : i + 1],
            lows=low[entry_i : i + 1],
        )
        trades.append(
            TradeRecord(
                entry_i=entry_i,
                exit_i=i,
                side=entry_side,
                entry_price=entry_px_net,
                exit_price=fill_px,
                qty=abs(held),
                pnl_gross=float(pnl_gross),
                pnl_net=float(pnl_net),
                mae=mae,
                mfe=mfe,
                exit_reason="signal" if i < n - 1 else "eod",
            )
        )
        held = 0.0
        entry_i = -1
        entry_comm = 0.0

    def _open_trade(i: int, target: float, px_mid: float) -> None:
        nonlocal cash_net, cash_gross, held, entry_i, entry_px_net, entry_px_gross
        nonlocal entry_side, entry_comm
        side: Literal["buy", "sell"] = "buy" if target > 0 else "sell"
        fill_px, fc = cost.one_way(
            price=px_mid,
            side=side,
            vol_proxy=float(atr[i]),
            in_session=bool(in_session[i]),
            size=abs(target),
        )
        fill_prices[i] = fill_px
        cash_net -= fill_px * target + fc.commission
        cash_gross -= px_mid * target
        held = target
        entry_i = i
        entry_side = 1 if target > 0 else -1
        entry_px_net = fill_px
        entry_px_gross = px_mid
        entry_comm = fc.commission

    for i in range(n):
        target = float(position[i]) * qty
        px_mid = open_[i]
        if target != held:
            if held != 0.0 and target == 0.0:
                _close_trade(i, px_mid)
            elif held == 0.0 and target != 0.0:
                _open_trade(i, target, px_mid)
            else:
                # flip
                _close_trade(i, px_mid)
                _open_trade(i, target, px_mid)
        equity_net[i] = cash_net + held * close[i]
        equity_gross[i] = cash_gross + held * close[i]

    if held != 0.0:
        _close_trade(n - 1, close[n - 1])
        equity_net[n - 1] = cash_net
        equity_gross[n - 1] = cash_gross

    t_net = np.array([t.pnl_net for t in trades], dtype=np.float64)
    t_gross = np.array([t.pnl_gross for t in trades], dtype=np.float64)
    metrics_net = compute_metrics(
        equity_net=equity_net,
        equity_gross=equity_gross,
        trade_pnls_net=t_net,
        trade_pnls_gross=t_gross,
        position=position.astype(np.float64),
        initial_cash=initial_cash,
    )
    metrics_gross = compute_metrics(
        equity_net=equity_gross,
        equity_gross=equity_gross,
        trade_pnls_net=t_gross,
        trade_pnls_gross=t_gross,
        position=position.astype(np.float64),
        initial_cash=initial_cash,
    )
    return BacktestResult(
        lane=lane,
        equity_net=equity_net,
        equity_gross=equity_gross,
        position=position,
        trades=trades,
        metrics_net=metrics_net,
        metrics_gross=metrics_gross,
        funnel=funnel,
        fill_prices=fill_prices,
    )
