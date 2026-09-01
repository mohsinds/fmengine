"""Ingestion pipeline: adapter → quality → catalog → snapshot → QuestDB."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fmtrader.core.enums import InstrumentClass, Side
from fmtrader.core.errors import DataError
from fmtrader.data.adapters.base import AdapterCapabilities
from fmtrader.data.adapters.registry import get_adapter
from fmtrader.data.calendars import get_calendar
from fmtrader.data.catalog import Catalog, SnapshotManifest, write_snapshot
from fmtrader.data.quality import QualityReport, print_coverage_table, run_quality_gate
from fmtrader.data.questdb_mirror import count_rows, mirror_frame, truncate_symbol
from fmtrader.system.logging import get_logger

log = get_logger("fmtrader.data.ingest")


@dataclass(frozen=True)
class IngestResult:
    """Outcome of a single ingest run."""

    manifest: SnapshotManifest
    quality: QualityReport
    parquet_rows: int
    questdb_rows: int | None


def ingest(
    *,
    adapter_name: str,
    path: Path,
    symbol: str,
    timeframe: str,
    instrument_class: InstrumentClass,
    side: Side | None,
    catalog_root: Path,
    snapshots_dir: Path,
    mirror_questdb: bool = True,
    print_coverage: bool = True,
) -> IngestResult:
    """Run the full ingest pipeline."""
    adapter = get_adapter(adapter_name)
    result = adapter.read(
        path,
        symbol=symbol,
        timeframe=timeframe,
        instrument_class=instrument_class,
        side=side,
    )
    caps: AdapterCapabilities = result.capabilities
    calendar = get_calendar(caps.session_calendar)

    annotated, quality = run_quality_gate(result.frame, calendar)
    if print_coverage:
        print_coverage_table(quality)

    catalog = Catalog(catalog_root)
    catalog_uri = str(catalog.write(annotated, symbol=symbol, timeframe=timeframe))
    parquet_rows = catalog.row_count(symbol=symbol, timeframe=timeframe)

    if parquet_rows != annotated.height:
        raise DataError(f"Catalog row mismatch: wrote {annotated.height}, read back {parquet_rows}")

    manifest = write_snapshot(
        snapshots_dir=snapshots_dir,
        frame=annotated,
        catalog_uri=catalog_uri,
        caps=caps,
        side=side.value if side else None,
        quality=quality,
        symbol=symbol,
        timeframe=timeframe,
        instrument_class=instrument_class.value,
    )
    log.info(
        "ingest_catalog_written",
        dataset_id=manifest.dataset_id,
        rows=manifest.rows,
        content_hash=manifest.content_hash,
    )

    qdb_rows: int | None = None
    if mirror_questdb:
        truncate_symbol(symbol=symbol, timeframe=timeframe)
        mirror_frame(annotated)
        qdb_rows = count_rows(symbol=symbol, timeframe=timeframe)
        if qdb_rows != parquet_rows:
            raise DataError(
                f"QuestDB/Parquet row mismatch: parquet={parquet_rows} questdb={qdb_rows}"
            )
        log.info("ingest_questdb_mirrored", rows=qdb_rows)

    return IngestResult(
        manifest=manifest,
        quality=quality,
        parquet_rows=parquet_rows,
        questdb_rows=qdb_rows,
    )


def load_manifest(snapshots_dir: Path, dataset_id: str) -> SnapshotManifest:
    path = snapshots_dir / f"{dataset_id}.json"
    if not path.is_file():
        raise DataError(f"Snapshot manifest not found: {path}")
    return SnapshotManifest.load(path)
