"""``fmtrader providers`` CLI."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from fmtrader.system.logging import configure_logging, get_logger

providers_app = typer.Typer(help="External feature providers (news, sentiment, fundamentals).")
console = Console()


def _bootstrap_default_providers() -> None:
    from fmtrader.providers.news_feed import NewsFeedProvider
    from fmtrader.providers.null import NullProvider
    from fmtrader.providers.optional_gated import OptionalDependencyProvider
    from fmtrader.providers.registry import default_registry, register_provider
    from fmtrader.providers.synthetic_news import SyntheticNewsProvider
    from fmtrader.providers.technical import TechnicalProvider

    reg = default_registry()
    if not reg.has("technical") and not reg.is_disabled("technical"):
        register_provider(TechnicalProvider())
    if not reg.has("synthetic_news") and not reg.is_disabled("synthetic_news"):
        register_provider(SyntheticNewsProvider())
    if not reg.has("news_feed") and not reg.is_disabled("news_feed"):
        register_provider(NewsFeedProvider())
    if not reg.has("null") and not reg.is_disabled("null"):
        register_provider(NullProvider())
    # Always attempt gated optional — demonstrates clean disable
    if not reg.has("optional_gated") and not reg.is_disabled("optional_gated"):
        register_provider(OptionalDependencyProvider())


@providers_app.command("list")
def providers_list() -> None:
    """Show registered providers and availability."""
    configure_logging()
    _bootstrap_default_providers()
    from fmtrader.providers.registry import default_registry

    table = Table(title="Feature providers")
    table.add_column("Name")
    table.add_column("Kind")
    table.add_column("Optional")
    table.add_column("Available")
    table.add_column("Reason")
    for s in default_registry().list_status():
        avail = "[green]yes[/green]" if s.available else "[red]no[/red]"
        table.add_row(s.name, s.kind, str(s.optional), avail, s.reason)
    console.print(table)


@providers_app.command("validate")
def providers_validate(
    provider: str = typer.Option(..., "--provider"),
    dataset: str = typer.Option(..., "--dataset"),
    catalog_root: Path = typer.Option(Path("data/catalog"), "--catalog-root"),
    snapshots_dir: Path = typer.Option(Path("data/snapshots"), "--snapshots-dir"),
    max_bars: int = typer.Option(500, "--max-bars"),
) -> None:
    """Fetch + align a provider against a dataset slice; check join health."""
    configure_logging()
    log = get_logger("fmtrader.providers")
    _bootstrap_default_providers()
    from fmtrader.data.catalog import Catalog, SnapshotManifest
    from fmtrader.providers.alignment import align_feature
    from fmtrader.providers.registry import default_registry

    snap = SnapshotManifest.load(snapshots_dir / f"{dataset}.json")
    bars = Catalog(catalog_root).read(symbol=snap.symbol, timeframe=snap.timeframe)
    if bars.height > max_bars:
        bars = bars.head(max_bars)
    prov = default_registry().get(provider)
    start = bars["ts"].min()
    end = bars["ts"].max()
    assert isinstance(start, datetime) and isinstance(end, datetime)
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    records = list(prov.fetch(snap.symbol, start, end))
    specs = prov.feature_specs()
    console.print(
        f"provider={provider} records={len(records)} specs={len(specs)} bars={bars.height}"
    )
    for spec in specs[:5]:
        series = align_feature(bars, records, spec)
        null_pct = series.null_count() / max(series.len(), 1)
        console.print(f"  {spec.name}: null_pct={null_pct:.3f} dtype={series.dtype}")
    log.info("providers_validate_done", provider=provider, records=len(records))
