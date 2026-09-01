"""Triple-barrier labeling, meta-label scaffold, and sample weights."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl

from fmtrader.core.errors import FeatureError
from fmtrader.features.indicators.volatility import atr


@dataclass(frozen=True)
class TripleBarrierConfig:
    """ATR-scaled triple-barrier parameters."""

    atr_period: int = 14
    pt_mult: float = 2.0  # profit-take = pt_mult * ATR
    sl_mult: float = 2.0  # stop-loss = sl_mult * ATR
    max_horizon: int = 60  # time barrier in bars
    min_ret: float = 0.0  # optional filter on |return|


def triple_barrier_labels(
    df: pl.DataFrame,
    cfg: TripleBarrierConfig | None = None,
) -> pl.DataFrame:
    """Label each bar by first barrier touch using future path (for supervised learning).

    Returns columns:
      - ``tb_label``: 1 (pt), -1 (sl), 0 (time)
      - ``tb_touch_bars``: bars until touch (inclusive of exit bar)
      - ``tb_ret``: close-to-exit close return
      - ``sample_weight``: uniqueness-based weight in (0, 1]

    Decision at bar ``t`` may only use information ≤ t; the label *outcome* uses
    (t, t+horizon] by construction. Features joined to these labels must not peek.
    """
    cfg = cfg or TripleBarrierConfig()
    if cfg.max_horizon < 1:
        raise FeatureError("max_horizon must be >= 1")
    if "close" not in df.columns or "high" not in df.columns or "low" not in df.columns:
        raise FeatureError("triple_barrier requires high/low/close")

    close = df["close"].to_numpy().astype(np.float64)
    high = df["high"].to_numpy().astype(np.float64)
    low = df["low"].to_numpy().astype(np.float64)
    atr_s = atr(df, period=cfg.atr_period).to_numpy().astype(np.float64)
    n = close.shape[0]

    labels = np.full(n, np.nan)
    touch = np.full(n, np.nan)
    rets = np.full(n, np.nan)
    # For uniqueness: for each bar j, count how many labels' windows cover j
    coverage = np.zeros(n, dtype=np.float64)

    for t in range(n):
        a = atr_s[t]
        if np.isnan(a) or a <= 0 or np.isnan(close[t]):
            continue
        pt = close[t] + cfg.pt_mult * a
        sl = close[t] - cfg.sl_mult * a
        end = min(n - 1, t + cfg.max_horizon)
        hit_label = 0
        hit_i = end
        for i in range(t + 1, end + 1):
            # First touch wins within the bar: check high/low vs barriers
            if high[i] >= pt and low[i] <= sl:
                # Ambiguous same-bar touch: favor stop (conservative)
                hit_label = -1
                hit_i = i
                break
            if high[i] >= pt:
                hit_label = 1
                hit_i = i
                break
            if low[i] <= sl:
                hit_label = -1
                hit_i = i
                break
        labels[t] = float(hit_label)
        touch[t] = float(hit_i - t)
        rets[t] = (close[hit_i] - close[t]) / close[t]
        coverage[t + 1 : hit_i + 1] += 1.0

    # Sample weight = mean inverse uniqueness over the label's active window
    weights = np.full(n, np.nan)
    for t in range(n):
        if np.isnan(labels[t]):
            continue
        hit_i = int(t + touch[t])
        window = coverage[t + 1 : hit_i + 1]
        if window.size == 0:
            weights[t] = 1.0
            continue
        inv = 1.0 / np.maximum(window, 1.0)
        weights[t] = float(np.mean(inv))

    out = pl.DataFrame(
        {
            "tb_label": labels,
            "tb_touch_bars": touch,
            "tb_ret": rets,
            "sample_weight": weights,
        }
    )
    return out.with_columns(
        pl.col("tb_label").cast(pl.Float64),
        pl.col("tb_touch_bars").cast(pl.Float64),
        pl.col("tb_ret").cast(pl.Float64),
        pl.col("sample_weight").cast(pl.Float64),
    )


def meta_labels(
    primary_side: pl.Series,
    tb: pl.DataFrame,
) -> pl.Series:
    """Meta-label: 1 if primary side matches profitable barrier outcome, else 0.

    ``primary_side`` is +1 / -1 / 0 (flat). When flat, meta-label is null.
    """
    if primary_side.len() != tb.height:
        raise FeatureError("primary_side length must match triple-barrier frame")
    side = primary_side.to_numpy().astype(np.float64)
    label = tb["tb_label"].to_numpy().astype(np.float64)
    out = np.full(side.shape[0], np.nan)
    mask = (side != 0) & ~np.isnan(label)
    out[mask] = np.where(side[mask] == label[mask], 1.0, 0.0)
    # Time-barrier (0) with matching side still counts as "take" only if side==0 skipped
    return pl.Series("meta_label", out)
