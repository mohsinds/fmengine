"""Backtest performance metrics (gross and net always reported together)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np


@dataclass
class Metrics:
    """Standard metric pack for one backtest run."""

    sharpe: float
    sortino: float
    calmar: float
    cagr: float
    max_drawdown: float
    max_drawdown_bars: int
    hit_rate: float
    profit_factor: float
    avg_win: float
    avg_loss: float
    expectancy: float
    turnover: float
    exposure: float
    trade_count: int
    gross_pnl: float
    net_pnl: float
    cost_drag_pct: float
    tail_ratio: float
    ulcer_index: float
    total_return_net: float
    total_return_gross: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    if b == 0.0 or np.isnan(b):
        return default
    return float(a / b)


def sharpe_ratio(returns: np.ndarray, *, periods_per_year: float = 365.25 * 24 * 60) -> float:
    """Annualized Sharpe of per-bar returns (M1 default periods)."""
    r = np.asarray(returns, dtype=np.float64)
    r = r[np.isfinite(r)]
    if r.size < 2:
        return 0.0
    mu = float(np.mean(r))
    sd = float(np.std(r, ddof=1))
    if sd == 0.0:
        return 0.0
    return float(np.sqrt(periods_per_year) * mu / sd)


def sortino_ratio(returns: np.ndarray, *, periods_per_year: float = 365.25 * 24 * 60) -> float:
    r = np.asarray(returns, dtype=np.float64)
    r = r[np.isfinite(r)]
    if r.size < 2:
        return 0.0
    mu = float(np.mean(r))
    downside = r[r < 0.0]
    if downside.size == 0:
        return float("inf") if mu > 0 else 0.0
    dd = float(np.std(downside, ddof=1))
    if dd == 0.0:
        return 0.0
    return float(np.sqrt(periods_per_year) * mu / dd)


def max_drawdown(equity: np.ndarray) -> tuple[float, int]:
    """Return (max_dd as positive fraction, duration in bars of that trough)."""
    eq = np.asarray(equity, dtype=np.float64)
    if eq.size == 0:
        return 0.0, 0
    peak = np.maximum.accumulate(eq)
    dd = (peak - eq) / np.where(peak == 0, np.nan, peak)
    dd = np.nan_to_num(dd, nan=0.0)
    i = int(np.argmax(dd))
    max_dd = float(dd[i])
    # duration: bars from last peak before i to i
    peak_i = int(np.argmax(eq[: i + 1])) if i > 0 else 0
    return max_dd, max(0, i - peak_i)


def cagr(equity: np.ndarray, *, bars_per_year: float = 365.25 * 24 * 60) -> float:
    eq = np.asarray(equity, dtype=np.float64)
    if eq.size < 2 or eq[0] <= 0 or eq[-1] <= 0:
        return 0.0
    years = eq.size / bars_per_year
    if years <= 0:
        return 0.0
    with np.errstate(over="ignore", invalid="ignore"):
        out = float((eq[-1] / eq[0]) ** (1.0 / years) - 1.0)
    if not np.isfinite(out):
        return 0.0
    return out


def ulcer_index(equity: np.ndarray) -> float:
    eq = np.asarray(equity, dtype=np.float64)
    if eq.size == 0:
        return 0.0
    peak = np.maximum.accumulate(eq)
    dd = 100.0 * (eq - peak) / np.where(peak == 0, np.nan, peak)
    dd = np.nan_to_num(dd, nan=0.0)
    return float(np.sqrt(np.mean(dd**2)))


def tail_ratio(returns: np.ndarray, q: float = 0.95) -> float:
    r = np.asarray(returns, dtype=np.float64)
    r = r[np.isfinite(r)]
    if r.size < 20:
        return 0.0
    right = float(np.quantile(r, q))
    left = float(np.abs(np.quantile(r, 1.0 - q)))
    return _safe_div(right, left)


def compute_metrics(
    *,
    equity_net: np.ndarray,
    equity_gross: np.ndarray,
    trade_pnls_net: np.ndarray,
    trade_pnls_gross: np.ndarray,
    position: np.ndarray,
    bars_per_year: float = 365.25 * 24 * 60,
) -> Metrics:
    """Build the mandatory metric pack from equity curves and trade P&Ls."""
    eq_n = np.asarray(equity_net, dtype=np.float64)
    eq_g = np.asarray(equity_gross, dtype=np.float64)
    rets_n = np.diff(eq_n, prepend=eq_n[0]) / np.where(eq_n == 0, np.nan, np.roll(eq_n, 1))
    rets_n[0] = 0.0
    rets_n = np.nan_to_num(rets_n, nan=0.0)

    t_net = np.asarray(trade_pnls_net, dtype=np.float64)
    t_gross = np.asarray(trade_pnls_gross, dtype=np.float64)
    wins = t_net[t_net > 0]
    losses = t_net[t_net < 0]
    hit = _safe_div(float(wins.size), float(t_net.size)) if t_net.size else 0.0
    pf = (
        _safe_div(float(wins.sum()), float(np.abs(losses.sum())))
        if losses.size
        else (float("inf") if wins.size else 0.0)
    )
    avg_win = float(wins.mean()) if wins.size else 0.0
    avg_loss = float(losses.mean()) if losses.size else 0.0
    expectancy = float(t_net.mean()) if t_net.size else 0.0

    pos = np.asarray(position, dtype=np.float64)
    exposure = float(np.mean(np.abs(pos) > 0)) if pos.size else 0.0
    # turnover: average absolute position change per bar
    turnover = float(np.mean(np.abs(np.diff(pos, prepend=0.0)))) if pos.size else 0.0

    gross_pnl = float(t_gross.sum()) if t_gross.size else float(eq_g[-1] - eq_g[0])
    net_pnl = float(t_net.sum()) if t_net.size else float(eq_n[-1] - eq_n[0])
    cost_drag = _safe_div(gross_pnl - net_pnl, abs(gross_pnl), default=0.0) * 100.0

    mdd, mdd_bars = max_drawdown(eq_n)
    sh = sharpe_ratio(rets_n, periods_per_year=bars_per_year)
    so = sortino_ratio(rets_n, periods_per_year=bars_per_year)
    cg = cagr(eq_n, bars_per_year=bars_per_year)
    calmar = _safe_div(cg, mdd) if mdd > 0 else 0.0

    return Metrics(
        sharpe=sh,
        sortino=so if np.isfinite(so) else 0.0,
        calmar=calmar,
        cagr=cg,
        max_drawdown=mdd,
        max_drawdown_bars=mdd_bars,
        hit_rate=hit,
        profit_factor=pf if np.isfinite(pf) else 0.0,
        avg_win=avg_win,
        avg_loss=avg_loss,
        expectancy=expectancy,
        turnover=turnover,
        exposure=exposure,
        trade_count=int(t_net.size),
        gross_pnl=gross_pnl,
        net_pnl=net_pnl,
        cost_drag_pct=cost_drag,
        tail_ratio=tail_ratio(rets_n),
        ulcer_index=ulcer_index(eq_n),
        total_return_net=_safe_div(eq_n[-1] - eq_n[0], eq_n[0]) if eq_n.size and eq_n[0] else 0.0,
        total_return_gross=_safe_div(eq_g[-1] - eq_g[0], eq_g[0]) if eq_g.size and eq_g[0] else 0.0,
    )
