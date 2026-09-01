"""``fmtrader features`` CLI — build and list feature sets."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from fmtrader.system.logging import configure_logging, get_logger

features_app = typer.Typer(help="Feature sets, indicators, and labeling.")
console = Console()


@features_app.command("build")
def features_build(
    dataset: str = typer.Option(..., "--dataset", help="Snapshot dataset_id"),
    set_path: Path = typer.Option(
        ...,
        "--set",
        help="Path to feature-set YAML",
        exists=True,
        dir_okay=False,
        readable=True,
    ),
    catalog_root: Path = typer.Option(Path("data/catalog"), "--catalog-root"),
    snapshots_dir: Path = typer.Option(Path("data/snapshots"), "--snapshots-dir"),
    features_root: Path = typer.Option(Path("data/features"), "--features-root"),
) -> None:
    """Validate YAML against dataset capabilities, build features, write store."""
    configure_logging()
    log = get_logger("fmtrader.features.cli")
    from fmtrader.features.pipeline import build_and_store

    manifest = build_and_store(
        dataset_id=dataset,
        feature_set_path=set_path,
        catalog_root=catalog_root,
        snapshots_dir=snapshots_dir,
        features_root=features_root,
    )
    console.print(
        f"Feature build complete name={manifest.feature_set_name} "
        f"version={manifest.feature_set_version} rows={manifest.rows} "
        f"cols={len(manifest.columns)} elapsed_s={manifest.elapsed_sec} "
        f"peak_gb={manifest.peak_memory_gb} hash={manifest.definition_hash}"
    )
    log.info("cli_features_build_done", dataset_id=dataset, version=manifest.feature_set_version)


@features_app.command("list")
def features_list(
    dataset: str = typer.Option(..., "--dataset", help="Snapshot dataset_id"),
    snapshots_dir: Path = typer.Option(Path("data/snapshots"), "--snapshots-dir"),
) -> None:
    """Show indicator availability for a dataset (gated capabilities)."""
    configure_logging()
    from fmtrader.features.pipeline import availability_report

    rows = availability_report(dataset_id=dataset, snapshots_dir=snapshots_dir)
    table = Table(title=f"Indicators vs {dataset}")
    table.add_column("Name")
    table.add_column("Category")
    table.add_column("Available")
    table.add_column("Reason")
    for r in rows:
        avail = "[green]yes[/green]" if r["available"] else "[red]no[/red]"
        table.add_row(r["name"], r["category"], avail, r["reason"])
    console.print(table)
