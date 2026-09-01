"""Futures revalidation — volume features unlock + strategy smoke on continuous GC."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

import fmtrader.features  # noqa: F401
from fmtrader.backtest.costs import CostModel
from fmtrader.backtest.vbt.runner import run_vectorbt_lane
from fmtrader.core.enums import InstrumentClass
from fmtrader.data.adapters.databento import DatabentoAdapter
from fmtrader.data.contracts import (
    AdjustmentMethod,
    FuturesContinuousSeriesBuilder,
    RollRule,
)
from fmtrader.features.registry import compute_indicator
from fmtrader.strategy.library.ema_cross import EmaCross

pytestmark = pytest.mark.integration


def _write_contract_csv(path: Path, symbol: str, *, start: date, n: int, vol_base: float) -> Path:
    lines = ["timestamp,open,high,low,close,volume,open_interest"]
    for i in range(n):
        d = start + timedelta(days=i)
        if d.weekday() >= 5:
            continue
        ts = int(datetime(d.year, d.month, d.day, 18, 0, tzinfo=UTC).timestamp() * 1000)
        px = 2000.0 + i * 0.25 + (0 if "Z" in symbol else 5.0)
        vol = vol_base + i * 2.0
        # Flip volume leadership mid-series for later contract
        if "G" in symbol and symbol.startswith("GCG"):
            vol = vol_base + i * 8.0
        lines.append(f"{ts},{px},{px + 0.5},{px - 0.5},{px},{vol},{vol * 10}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _load_raw(tmp_path: Path) -> dict[str, pl.DataFrame]:
    adapter = DatabentoAdapter()
    out: dict[str, pl.DataFrame] = {}
    for sym, start, vol in (
        ("GCZ24", date(2024, 10, 1), 100.0),
        ("GCG25", date(2024, 10, 1), 20.0),
    ):
        csv = _write_contract_csv(tmp_path / f"{sym}.csv", sym, start=start, n=40, vol_base=vol)
        result = adapter.read(
            csv,
            symbol=sym,
            timeframe="1d",
            instrument_class=InstrumentClass.FUTURES_RAW,
        )
        out[sym] = result.frame.with_columns(pl.lit(True).alias("is_tradable"))
    return out


def test_volume_features_become_available(tmp_path: Path) -> None:
    caps = DatabentoAdapter().capabilities()
    assert caps.has_volume and caps.has_open_interest
    raw = _load_raw(tmp_path)
    built = FuturesContinuousSeriesBuilder().build(
        raw,
        adjustment=AdjustmentMethod.BACK_ADJUSTED,
        roll_rule=RollRule.VOLUME_CROSSOVER,
    )
    frame = built.continuous
    assert "volume" in frame.columns
    assert frame["volume"].null_count() == 0


def test_previously_gated_indicators_now_compute(tmp_path: Path) -> None:
    caps = DatabentoAdapter().capabilities()
    raw = _load_raw(tmp_path)
    built = FuturesContinuousSeriesBuilder().build(
        raw,
        adjustment=AdjustmentMethod.BACK_ADJUSTED,
        roll_rule=RollRule.VOLUME_CROSSOVER,
    )
    frame = built.continuous
    vwap = compute_indicator("vwap", frame, caps=caps, dataset_id="gc_synth", period=5)
    obv = compute_indicator("obv", frame, caps=caps, dataset_id="gc_synth")
    mfi = compute_indicator("mfi", frame, caps=caps, dataset_id="gc_synth", period=5)
    assert vwap.null_count() < vwap.len()
    assert obv.len() == frame.height
    assert mfi.null_count() < mfi.len()

    # Re-validate ema_cross (XAUUSD pipeline survivor) on futures continuous
    strat = EmaCross()
    pos = strat.generate(frame, {"fast": 3, "slow": 8}).to_numpy()
    from fmtrader.backtest.costs import CostModelConfig

    cost = CostModel(CostModelConfig(spread_abs=0.1, slippage_base_abs=0.05, commission_bps=0.5))
    result = run_vectorbt_lane(frame, pos, cost)
    # Spot vs futures will differ; require a completed net metrics object
    assert result.metrics_net.trade_count >= 0
    assert result.metrics_net.total_return_net == result.metrics_net.total_return_net  # not NaN
