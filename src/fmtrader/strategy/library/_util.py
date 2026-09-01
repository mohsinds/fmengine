"""Shared strategy helpers."""

from __future__ import annotations

import numpy as np
import polars as pl


def apply_tradable_hold(pos: np.ndarray, bars: pl.DataFrame) -> np.ndarray:
    """On non-tradable bars, hold prior desired position (no new flips)."""
    if "is_tradable" not in bars.columns:
        return pos
    out = pos.astype(np.int8, copy=True)
    tradable = bars["is_tradable"].to_numpy()
    for i in range(len(out)):
        if not tradable[i]:
            out[i] = out[i - 1] if i else 0
    return out
