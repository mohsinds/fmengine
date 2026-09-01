"""Holdout vault unit tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from fmtrader.backtest.validation.holdout import HoldoutVault, split_research_holdout
from fmtrader.core.errors import HoldoutError
from fmtrader.data.catalog import Catalog


def test_catalog_read_without_token_raises(tmp_path: Path) -> None:
    # Build a multi-year catalog so the vault applies
    t0 = datetime(2021, 1, 1, tzinfo=UTC)
    ts = [t0 + timedelta(days=i) for i in range(800)]  # ~2.2 years
    frame = pl.DataFrame(
        {
            "ts": ts,
            "open": [1.0] * 800,
            "high": [1.0] * 800,
            "low": [1.0] * 800,
            "close": [1.0] * 800,
            "symbol": ["X"] * 800,
            "timeframe": ["1d"] * 800,
            "instrument_class": ["spot_cfd"] * 800,
            "volume": [None] * 800,
            "open_interest": [None] * 800,
            "bid": [1.0] * 800,
            "ask": [None] * 800,
            "is_tradable": [True] * 800,
        }
    )
    cat = Catalog(tmp_path / "catalog")
    cat.write(frame, symbol="X", timeframe="1d")
    research = cat.read(symbol="X", timeframe="1d", exclude_holdout=True)
    assert research.height < 800
    with pytest.raises(HoldoutError, match="Holdout vault locked"):
        cat.read(symbol="X", timeframe="1d", exclude_holdout=False)


def test_no_public_api_path_returns_holdout_data(tmp_path: Path) -> None:
    t0 = datetime(2021, 1, 1, tzinfo=UTC)
    ts = [t0 + timedelta(days=i) for i in range(800)]
    frame = pl.DataFrame({"ts": ts, "close": list(range(800))})
    research, holdout, start = split_research_holdout(frame)
    assert holdout.height > 0
    assert research.filter(pl.col("ts") >= start).height == 0


def test_unlock_is_logged_with_justification(tmp_path: Path) -> None:
    vault = HoldoutVault(tmp_path / "holdout")
    token = vault.issue_token(
        strategy="ema_cross",
        dataset_id="ds",
        justification="Phase 5 unit test unlock",
    )
    vault.consume(token)
    log = (tmp_path / "holdout" / "unlocks.jsonl").read_text()
    assert "Phase 5 unit test unlock" in log
    assert "consumed" in log


def test_second_unlock_for_same_strategy_rejected(tmp_path: Path) -> None:
    vault = HoldoutVault(tmp_path / "holdout")
    t1 = vault.issue_token(strategy="s1", dataset_id="ds", justification="first")
    vault.consume(t1)
    with pytest.raises(HoldoutError, match="second unlock rejected"):
        vault.issue_token(strategy="s1", dataset_id="ds", justification="again")
