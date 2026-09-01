"""CLI commands for ``fmtrader data …``."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from fmtrader.core.enums import InstrumentClass, Side
from fmtrader.data.catalog import Catalog
from fmtrader.data.ingest import ingest, load_manifest
from fmtrader.data.quality import print_coverage_table
from fmtrader.system.logging import configure_logging, get_logger

data_app = typer.Typer(help="Data ingestion, quality, and catalog commands.")
console = Console()

ROOT = Path.cwd()
DEFAULT_CATALOG = ROOT / "data" / "catalog"
DEFAULT_SNAPSHOTS = ROOT / "data" / "snapshots"


@data_app.command("ingest")
def data_ingest(
    adapter: str = typer.Option(..., "--adapter", help="Vendor adapter name"),
    path: Path = typer.Option(..., "--path", exists=True, dir_okay=False, readable=True),
    symbol: str = typer.Option(..., "--symbol"),
    timeframe: str = typer.Option("1m", "--timeframe"),
    instrument_class: InstrumentClass = typer.Option(
        InstrumentClass.SPOT_CFD, "--instrument-class"
    ),
    side: Side | None = typer.Option(None, "--side"),
    catalog_root: Path = typer.Option(DEFAULT_CATALOG, "--catalog-root"),
    snapshots_dir: Path = typer.Option(DEFAULT_SNAPSHOTS, "--snapshots-dir"),
    no_questdb: bool = typer.Option(False, "--no-questdb", help="Skip QuestDB mirror"),
) -> None:
    """Ingest a vendor file into the canonical catalog (+ optional QuestDB)."""
    configure_logging()
    log = get_logger("fmtrader.cli.data")
    result = ingest(
        adapter_name=adapter,
        path=path,
        symbol=symbol,
        timeframe=timeframe,
        instrument_class=instrument_class,
        side=side,
        catalog_root=catalog_root,
        snapshots_dir=snapshots_dir,
        mirror_questdb=not no_questdb,
        print_coverage=True,
    )
    console.print(
        f"[green]Ingest complete[/green] dataset_id={result.manifest.dataset_id} "
        f"rows={result.parquet_rows} hash={result.manifest.content_hash}"
    )
    if result.questdb_rows is not None:
        console.print(f"QuestDB rows={result.questdb_rows}")
    log.info("cli_ingest_done", dataset_id=result.manifest.dataset_id)


@data_app.command("quality")
def data_quality(
    dataset: str = typer.Option(..., "--dataset", help="dataset_id from snapshot manifest"),
    snapshots_dir: Path = typer.Option(DEFAULT_SNAPSHOTS, "--snapshots-dir"),
) -> None:
    """Print the stored quality/coverage report for a dataset."""
    configure_logging()
    from fmtrader.data.quality import QualityReport

    manifest = load_manifest(snapshots_dir, dataset)
    qr = QualityReport(**manifest.quality_report)
    print_coverage_table(qr)
    console.print(
        f"has_volume={manifest.has_volume} has_spread={manifest.has_spread} "
        f"side={manifest.side} rows={manifest.rows}"
    )


@data_app.command("continuous")
def data_continuous(
    contracts_dir: Path = typer.Option(
        ...,
        "--contracts-dir",
        exists=True,
        file_okay=False,
        help="Directory of per-contract CSV/Parquet files (symbol in filename stem)",
    ),
    continuous_symbol: str = typer.Option("GC_c1", "--continuous-symbol"),
    timeframe: str = typer.Option("1d", "--timeframe"),
    adjustment: str = typer.Option("back_adjusted", "--adjustment"),
    roll_rule: str = typer.Option("volume_crossover", "--roll-rule"),
    out_dir: Path = typer.Option(ROOT / "data" / "continuous", "--out-dir"),
    confirm_days: int = typer.Option(1, "--confirm-days"),
) -> None:
    """Build a continuous futures series from raw per-contract files; retain raws."""
    configure_logging()
    from fmtrader.core.enums import InstrumentClass
    from fmtrader.data.adapters.databento import DatabentoAdapter
    from fmtrader.data.contracts import (
        AdjustmentMethod,
        FuturesContinuousSeriesBuilder,
        RollRule,
        write_raw_and_continuous,
    )

    adapter = DatabentoAdapter()
    import polars as pl

    raw: dict[str, pl.DataFrame] = {}
    for path in sorted(contracts_dir.iterdir()):
        if path.suffix.lower() not in {".csv", ".parquet", ".pq"}:
            continue
        sym = path.stem.split("_")[0].upper()
        result = adapter.read(
            path,
            symbol=sym,
            timeframe=timeframe,
            instrument_class=InstrumentClass.FUTURES_RAW,
        )
        raw[sym] = result.frame
    if len(raw) < 1:
        raise typer.BadParameter(f"No contract files found in {contracts_dir}")

    built = FuturesContinuousSeriesBuilder().build(
        raw,
        adjustment=AdjustmentMethod(adjustment),
        roll_rule=RollRule(roll_rule),
        roll_params={"confirm_days": confirm_days},
    )
    paths = write_raw_and_continuous(
        built,
        root=out_dir / continuous_symbol,
        continuous_symbol=continuous_symbol,
        timeframe=timeframe,
    )
    console.print(
        f"[green]Continuous series written[/green] {paths[continuous_symbol]} "
        f"rolls={len(built.rolls)} raw_contracts={len(built.raw_by_contract)}"
    )


@data_app.command("catalog-count")
def catalog_count(
    symbol: str = typer.Option(..., "--symbol"),
    timeframe: str = typer.Option("1m", "--timeframe"),
    catalog_root: Path = typer.Option(DEFAULT_CATALOG, "--catalog-root"),
) -> None:
    """Print Parquet catalog row count."""
    n = Catalog(catalog_root).row_count(symbol=symbol, timeframe=timeframe)
    console.print(n)
