"""Canonical Parquet catalog + snapshot manifests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from fmtrader.core.errors import DataError
from fmtrader.data.adapters.base import AdapterCapabilities
from fmtrader.data.quality import QualityReport


@dataclass(frozen=True)
class SnapshotManifest:
    """Immutable dataset identity for reproducible experiments."""

    dataset_id: str
    content_hash: str
    source: str
    side: str | None
    rows: int
    start: str | None
    end: str | None
    has_volume: bool
    has_spread: bool
    has_open_interest: bool
    quality_report: dict[str, Any]
    created_at: str
    symbol: str
    timeframe: str
    instrument_class: str
    catalog_uri: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "content_hash": self.content_hash,
            "source": self.source,
            "side": self.side,
            "rows": self.rows,
            "start": self.start,
            "end": self.end,
            "has_volume": self.has_volume,
            "has_spread": self.has_spread,
            "has_open_interest": self.has_open_interest,
            "quality_report": self.quality_report,
            "created_at": self.created_at,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "instrument_class": self.instrument_class,
            "catalog_uri": self.catalog_uri,
        }

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Stable key order for reproducibility
        payload = json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"
        path.write_text(payload, encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> SnapshotManifest:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(**data)


def content_hash_frame(frame: pl.DataFrame) -> str:
    """SHA-256 over canonical Arrow IPC bytes (stable column order + sorted by ts)."""
    from io import BytesIO

    cols = ["ts", *sorted(c for c in frame.columns if c != "ts")]
    ordered = frame.select([c for c in cols if c in frame.columns]).sort("ts")
    buf = BytesIO()
    ordered.write_ipc(buf)
    digest = hashlib.sha256(buf.getvalue()).hexdigest()
    return f"sha256:{digest}"


def dataset_id_for(
    *,
    symbol: str,
    timeframe: str,
    side: str | None,
    start: str | None,
    end: str | None,
) -> str:
    """Build a stable dataset_id from identity fields."""
    sym = symbol.lower()
    side_part = f"_{side}" if side else ""
    start_d = (start or "unknown")[:10]
    end_d = (end or "unknown")[:10]
    return f"{sym}_{timeframe}{side_part}_{start_d}_{end_d}".replace(":", "-")


def catalog_partition_path(root: Path, *, symbol: str, timeframe: str, ts: datetime) -> Path:
    return (
        root
        / f"symbol={symbol}"
        / f"timeframe={timeframe}"
        / f"year={ts.year:04d}"
        / f"month={ts.month:02d}"
    )


class Catalog:
    """Read/write partitioned Parquet under ``data/catalog``."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def write(self, frame: pl.DataFrame, *, symbol: str, timeframe: str) -> Path:
        if frame.is_empty():
            raise DataError("Refusing to write empty frame to catalog")
        if "ts" not in frame.columns:
            raise DataError("Catalog frame missing ts column")

        # Partition by year/month of ts
        partitioned = frame.with_columns(
            pl.col("ts").dt.year().alias("year"),
            pl.col("ts").dt.month().alias("month"),
        )
        base = self.root / f"symbol={symbol}" / f"timeframe={timeframe}"
        # Overwrite symbol/timeframe tree for idempotent re-ingest
        if base.exists():
            import shutil

            shutil.rmtree(base)

        parts = partitioned.partition_by(["year", "month"], as_dict=True, include_key=True)
        for key, part in parts.items():
            if isinstance(key, tuple):
                year, month = int(key[0]), int(key[1])
            else:
                raise DataError(f"Unexpected partition key: {key!r}")
            out_dir = base / f"year={year:04d}" / f"month={month:02d}"
            out_dir.mkdir(parents=True, exist_ok=True)
            part.drop(["year", "month"]).sort("ts").write_parquet(
                out_dir / "bars.parquet", compression="zstd"
            )
        return base

    def read(
        self,
        *,
        symbol: str,
        timeframe: str,
        columns: list[str] | None = None,
    ) -> pl.DataFrame:
        base = self.root / f"symbol={symbol}" / f"timeframe={timeframe}"
        if not base.exists():
            raise DataError(f"Catalog path not found: {base}")
        frame = pl.read_parquet(base / "**" / "bars.parquet", columns=columns)
        return frame.sort("ts")

    def row_count(self, *, symbol: str, timeframe: str) -> int:
        return self.read(symbol=symbol, timeframe=timeframe).height


def write_snapshot(
    *,
    snapshots_dir: Path,
    frame: pl.DataFrame,
    catalog_uri: str,
    caps: AdapterCapabilities,
    side: str | None,
    quality: QualityReport,
    symbol: str,
    timeframe: str,
    instrument_class: str,
) -> SnapshotManifest:
    """Persist manifest JSON next to the catalog write."""
    c_hash = content_hash_frame(frame)
    ds_id = dataset_id_for(
        symbol=symbol,
        timeframe=timeframe,
        side=side,
        start=quality.start,
        end=quality.end,
    )
    manifest = SnapshotManifest(
        dataset_id=ds_id,
        content_hash=c_hash,
        source=caps.source,
        side=side,
        rows=frame.height,
        start=quality.start,
        end=quality.end,
        has_volume=caps.has_volume,
        has_spread=caps.has_spread,
        has_open_interest=caps.has_open_interest,
        quality_report=quality.to_dict(),
        created_at=datetime.now(tz=UTC).isoformat(),
        symbol=symbol,
        timeframe=timeframe,
        instrument_class=instrument_class,
        catalog_uri=catalog_uri,
    )
    manifest.write(snapshots_dir / f"{ds_id}.json")
    return manifest
