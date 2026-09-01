"""End-to-end ingest integration tests (small synthetic CSV)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fmtrader.core.enums import InstrumentClass, Side
from fmtrader.data.catalog import Catalog
from fmtrader.data.ingest import ingest
from fmtrader.data.questdb_mirror import count_rows

pytestmark = pytest.mark.integration


def _synth_csv(path: Path, n: int = 120) -> Path:
    t0 = datetime(2021, 1, 4, 12, 0, tzinfo=UTC)
    lines = ["timestamp,open,high,low,close"]
    for i in range(n):
        ts_ms = int((t0 + timedelta(minutes=i)).timestamp() * 1000)
        px = 1800.0 + i * 0.01
        lines.append(f"{ts_ms},{px},{px + 0.1},{px - 0.1},{px}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_full_ingest_produces_manifest(tmp_path: Path) -> None:
    csv = _synth_csv(tmp_path / "x.csv")
    catalog = tmp_path / "catalog"
    snaps = tmp_path / "snapshots"
    result = ingest(
        adapter_name="dukascopy",
        path=csv,
        symbol="XAUUSD",
        timeframe="1m",
        instrument_class=InstrumentClass.SPOT_CFD,
        side=Side.BID,
        catalog_root=catalog,
        snapshots_dir=snaps,
        mirror_questdb=True,
        print_coverage=False,
    )
    assert (snaps / f"{result.manifest.dataset_id}.json").is_file()
    assert result.manifest.has_volume is False
    assert result.manifest.has_spread is False
    assert result.manifest.side == "bid"
    assert result.parquet_rows == 120


def test_questdb_row_count_matches_parquet(tmp_path: Path) -> None:
    csv = _synth_csv(tmp_path / "x.csv", n=60)
    catalog = tmp_path / "catalog"
    snaps = tmp_path / "snapshots"
    result = ingest(
        adapter_name="dukascopy",
        path=csv,
        symbol="XAUUSD",
        timeframe="1m",
        instrument_class=InstrumentClass.SPOT_CFD,
        side=Side.BID,
        catalog_root=catalog,
        snapshots_dir=snaps,
        mirror_questdb=True,
        print_coverage=False,
    )
    assert result.questdb_rows == result.parquet_rows
    assert count_rows(symbol="XAUUSD", timeframe="1m") == result.parquet_rows


def test_reingest_is_idempotent(tmp_path: Path) -> None:
    csv = _synth_csv(tmp_path / "x.csv", n=60)
    catalog = tmp_path / "catalog"
    snaps = tmp_path / "snapshots"
    kwargs = dict(
        adapter_name="dukascopy",
        path=csv,
        symbol="XAUUSD",
        timeframe="1m",
        instrument_class=InstrumentClass.SPOT_CFD,
        side=Side.BID,
        catalog_root=catalog,
        snapshots_dir=snaps,
        mirror_questdb=True,
        print_coverage=False,
    )
    a = ingest(**kwargs)  # type: ignore[arg-type]
    b = ingest(**kwargs)  # type: ignore[arg-type]
    assert a.parquet_rows == b.parquet_rows
    assert Catalog(catalog).row_count(symbol="XAUUSD", timeframe="1m") == a.parquet_rows
    # QuestDB should not accumulate duplicates
    assert count_rows(symbol="XAUUSD", timeframe="1m") == a.parquet_rows
