"""Fidelity lane — bar-by-bar event-driven fills (Nautilus-compatible semantics).

Uses the same next-bar open fill model as the triage lane so buy-and-hold and
simple signal strategies can parity-check. A full NautilusTrader venue adapter
plugs in here later without changing strategy code.
"""

from __future__ import annotations

import numpy as np
import polars as pl

from fmtrader.backtest.costs import CostModel
from fmtrader.backtest.engine import BacktestResult, run_next_bar_engine


def run_nautilus_lane(
    bars: pl.DataFrame,
    desired_position: np.ndarray,
    cost: CostModel,
    *,
    initial_cash: float = 100_000.0,
    qty: float = 1.0,
) -> BacktestResult:
    """Fidelity lane: explicit bar-loop (event-driven) next-bar fills."""
    # Intentionally call the shared engine; the loop below documents the event model
    # and keeps a seam for a future NautilusTrader adapter.
    _ = _event_loop_validate(bars, desired_position)
    return run_next_bar_engine(
        bars,
        desired_position,
        cost,
        lane="nautilus",
        initial_cash=initial_cash,
        qty=qty,
    )


def _event_loop_validate(bars: pl.DataFrame, desired: np.ndarray) -> int:
    """Walk bars event-style and count intended order events (no fills here)."""
    n = bars.height
    events = 0
    prev = 0
    for i in range(n):
        d = int(desired[i])
        if d != prev:
            events += 1
            prev = d
    return events
