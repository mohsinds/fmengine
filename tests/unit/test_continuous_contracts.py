"""Continuous futures contract construction tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from fmtrader.core.errors import DataError
from fmtrader.data.contracts import (
    AdjustmentMethod,
    FuturesContinuousSeriesBuilder,
    RollRule,
    assert_rolls_causal,
    decide_volume_rolls,
    leaky_volume_roll_using_future,
    write_raw_and_continuous,
)


def _weekday_contract(
    symbol: str,
    *,
    start: date,
    n_sessions: int,
    base: float,
    volumes: list[float],
    oi: list[float] | None = None,
) -> pl.DataFrame:
    assert len(volumes) == n_sessions
    rows = []
    d = start
    i = 0
    while i < n_sessions:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        px = base + i * 0.5
        ts = datetime(d.year, d.month, d.day, 18, 0, tzinfo=UTC)
        rows.append(
            {
                "ts": ts,
                "symbol": symbol,
                "instrument_class": "futures_raw",
                "timeframe": "1d",
                "open": px,
                "high": px + 1.0,
                "low": px - 1.0,
                "close": px,
                "volume": volumes[i],
                "open_interest": (oi or volumes)[i],
                "bid": None,
                "ask": None,
            }
        )
        i += 1
        d += timedelta(days=1)
    return pl.DataFrame(rows)


def _two_contract_fixture() -> dict[str, pl.DataFrame]:
    """GCZ24 front early; GCG25 takes volume lead from session index 5 onward."""
    start = date(2024, 11, 1)  # Friday
    n = 10
    vol_front = [100.0, 100.0, 90.0, 80.0, 70.0, 40.0, 30.0, 20.0, 10.0, 10.0]
    vol_back = [10.0, 20.0, 30.0, 40.0, 50.0, 80.0, 90.0, 100.0, 110.0, 120.0]
    front = _weekday_contract("GCZ24", start=start, n_sessions=n, base=2000.0, volumes=vol_front)
    back = _weekday_contract("GCG25", start=start, n_sessions=n, base=2010.0, volumes=vol_back)
    return {"GCZ24": front, "GCG25": back}


def test_volume_crossover_roll_selects_correct_contract() -> None:
    raw = _two_contract_fixture()
    rolls = decide_volume_rolls(raw, confirm_days=1)
    assert len(rolls) == 1
    assert rolls[0].from_contract == "GCZ24"
    assert rolls[0].to_contract == "GCG25"
    # Session index 5: first day back volume (80) > front (40)
    assert rolls[0].roll_date == date(2024, 11, 8)  # Fri Nov1 + weekends → session 5
    assert rolls[0].metric_to > rolls[0].metric_from


def test_panama_adjustment_preserves_price_differences() -> None:
    raw = _two_contract_fixture()
    result = FuturesContinuousSeriesBuilder().build(
        raw,
        adjustment=AdjustmentMethod.BACK_ADJUSTED,
        roll_rule=RollRule.VOLUME_CROSSOVER,
    )
    cont = result.continuous.sort("ts")
    # Within first active-contract segment, adjusted diffs == raw diffs
    front_sym = "GCZ24"
    seg = cont.filter(pl.col("active_contract") == front_sym)
    front_ts = set(seg["ts"].to_list())
    raw_f = raw[front_sym].filter(pl.col("ts").is_in(front_ts)).sort("ts")
    assert seg.height >= 2
    adj_diff = seg["close"].diff().drop_nulls()
    raw_diff = raw_f["close"].diff().drop_nulls()
    assert adj_diff.to_list() == pytest.approx(raw_diff.to_list())


def test_ratio_adjustment_preserves_returns() -> None:
    raw = _two_contract_fixture()
    result = FuturesContinuousSeriesBuilder().build(
        raw,
        adjustment=AdjustmentMethod.RATIO_ADJUSTED,
        roll_rule=RollRule.VOLUME_CROSSOVER,
    )
    cont = result.continuous.sort("ts")
    front_sym = "GCZ24"
    seg = cont.filter(pl.col("active_contract") == front_sym)
    front_ts = set(seg["ts"].to_list())
    raw_f = raw[front_sym].filter(pl.col("ts").is_in(front_ts)).sort("ts")
    assert seg.height >= 2
    adj_ret = (seg["close"] / seg["close"].shift(1) - 1.0).drop_nulls()
    raw_ret = (raw_f["close"] / raw_f["close"].shift(1) - 1.0).drop_nulls()
    assert adj_ret.to_list() == pytest.approx(raw_ret.to_list(), abs=1e-12)


def test_roll_uses_only_information_available_at_roll_date() -> None:
    raw = _two_contract_fixture()
    causal = decide_volume_rolls(raw, confirm_days=1)
    assert_rolls_causal(causal, raw, metric="volume")

    leaky = leaky_volume_roll_using_future(raw, look_ahead_days=3)
    assert leaky, "fixture must produce at least one leaky roll"
    with pytest.raises(DataError, match=r"look-ahead|not available"):
        assert_rolls_causal(leaky, raw, metric="volume")


def test_raw_contracts_retained_alongside_continuous(tmp_path: Path) -> None:
    raw = _two_contract_fixture()
    result = FuturesContinuousSeriesBuilder().build(
        raw,
        adjustment=AdjustmentMethod.BACK_ADJUSTED,
        roll_rule=RollRule.VOLUME_CROSSOVER,
    )
    assert set(result.raw_by_contract) == {"GCZ24", "GCG25"}
    assert result.continuous.height > 0
    paths = write_raw_and_continuous(
        result,
        root=tmp_path / "gc_cont",
        continuous_symbol="GC_c1",
        timeframe="1d",
    )
    assert (tmp_path / "gc_cont" / "raw_contracts" / "GCZ24_1d.parquet").is_file()
    assert (tmp_path / "gc_cont" / "raw_contracts" / "GCG25_1d.parquet").is_file()
    assert paths["GC_c1"].is_file()
    assert paths["rolls"].is_file()
    # Raw row counts unchanged
    assert result.raw_by_contract["GCZ24"].height == raw["GCZ24"].height
