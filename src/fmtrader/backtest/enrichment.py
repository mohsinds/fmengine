"""Per-trade enrichment captured at trade close (MAE/MFE/exit reason)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

import numpy as np

ExitReason = Literal["target", "stop", "time", "signal", "eod"]


@dataclass
class TradeRecord:
    entry_i: int
    exit_i: int
    side: int  # +1 long / -1 short
    entry_price: float
    exit_price: float
    qty: float
    pnl_gross: float
    pnl_net: float
    mae: float  # max adverse excursion (positive magnitude)
    mfe: float  # max favorable excursion
    exit_reason: ExitReason
    session_bucket: int | None = None
    regime: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_mae_mfe(
    *,
    side: int,
    entry_price: float,
    highs: np.ndarray,
    lows: np.ndarray,
) -> tuple[float, float]:
    """MAE/MFE in price units over the trade's held bars (entry..exit inclusive)."""
    if highs.size == 0:
        return 0.0, 0.0
    if side > 0:
        mfe = float(np.max(highs) - entry_price)
        mae = float(entry_price - np.min(lows))
    else:
        mfe = float(entry_price - np.min(lows))
        mae = float(np.max(highs) - entry_price)
    return max(mae, 0.0), max(mfe, 0.0)
