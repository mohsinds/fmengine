"""Fast triage lane (vectorized). Named vectorbt in the CLI for architecture fit.

Uses the shared next-bar engine; optionally accelerates sweeps via NumPy batching.
The ``vectorbt`` package is optional — current plotly pins break its import on this stack.
"""

from __future__ import annotations

import numpy as np
import polars as pl

from fmtrader.backtest.costs import CostModel
from fmtrader.backtest.engine import BacktestResult, run_next_bar_engine


def run_vectorbt_lane(
    bars: pl.DataFrame,
    desired_position: np.ndarray,
    cost: CostModel,
    *,
    initial_cash: float = 100_000.0,
    qty: float = 1.0,
) -> BacktestResult:
    """Triage lane: vectorized next-bar simulation."""
    return run_next_bar_engine(
        bars,
        desired_position,
        cost,
        lane="vectorbt",
        initial_cash=initial_cash,
        qty=qty,
    )
