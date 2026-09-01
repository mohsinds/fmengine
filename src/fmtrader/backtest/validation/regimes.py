"""Regime segmentation for performance reporting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import polars as pl

from fmtrader.backtest.metrics import compute_metrics

REGIME_BOUNDS: list[tuple[str, datetime, datetime]] = [
    ("2021", datetime(2021, 1, 1, tzinfo=UTC), datetime(2022, 1, 1, tzinfo=UTC)),
    ("2022", datetime(2022, 1, 1, tzinfo=UTC), datetime(2023, 1, 1, tzinfo=UTC)),
    ("2023-24", datetime(2023, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC)),
    ("2025-26", datetime(2025, 1, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC)),
]


@dataclass
class RegimeReport:
    by_regime: dict[str, dict[str, Any]]
    single_regime_only: bool
    label: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "by_regime": self.by_regime,
            "single_regime_only": self.single_regime_only,
            "label": self.label,
        }


def regime_for_ts(ts: datetime) -> str | None:
    ts = ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)
    for name, lo, hi in REGIME_BOUNDS:
        if lo <= ts < hi:
            return name
    return None


def segment_equity_by_regime(
    bars: pl.DataFrame,
    equity_net: np.ndarray,
    equity_gross: np.ndarray,
    position: np.ndarray,
) -> RegimeReport:
    """Compute simple return metrics per calendar regime."""
    ts = bars["ts"].to_list()
    by: dict[str, dict[str, Any]] = {}
    positive_regimes = 0
    for name, lo, hi in REGIME_BOUNDS:
        idx = [i for i, t in enumerate(ts) if lo <= t.astimezone(UTC) < hi]
        if len(idx) < 2:
            continue
        eq_n = equity_net[idx]
        eq_g = equity_gross[idx]
        pos = position[idx]
        # Normalize to start at first equity in regime
        m = compute_metrics(
            equity_net=eq_n,
            equity_gross=eq_g,
            trade_pnls_net=np.array([]),
            trade_pnls_gross=np.array([]),
            position=pos,
        )
        by[name] = {
            "total_return_net": m.total_return_net,
            "sharpe": m.sharpe,
            "bars": len(idx),
        }
        if m.total_return_net > 0:
            positive_regimes += 1

    single = positive_regimes <= 1 and len(by) > 1
    label = "regime_specific" if single else None
    return RegimeReport(by_regime=by, single_regime_only=single, label=label)
