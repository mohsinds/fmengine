"""Typer CLI entrypoint for ``fmtrader``."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from fmtrader.system.health import run_all_health_checks
from fmtrader.system.logging import configure_logging, get_logger
from fmtrader.system.memory import collect_memory_snapshot

app = typer.Typer(
    name="fmtrader",
    help="FinnMetrics quantitative research and execution engine.",
    no_args_is_help=True,
)
system_app = typer.Typer(help="Infrastructure health and resource probes.")
app.add_typer(system_app, name="system")

# Lazily import data CLI to keep `system` commands light
from fmtrader.backtest.cli import backtest_app  # noqa: E402
from fmtrader.data.cli import data_app  # noqa: E402
from fmtrader.execution.cli import execution_app  # noqa: E402
from fmtrader.features.cli import features_app  # noqa: E402

app.add_typer(data_app, name="data")
app.add_typer(features_app, name="features")
app.add_typer(backtest_app, name="backtest")
app.add_typer(execution_app, name="execution")

console = Console()


@system_app.command("health")
def system_health() -> None:
    """Check QuestDB, Postgres, Temporal, Redis, MLflow, and Ollama."""
    configure_logging()
    log = get_logger("fmtrader.cli")
    results = run_all_health_checks()
    table = Table(title="fmengine health")
    table.add_column("Service")
    table.add_column("Status")
    table.add_column("Latency (ms)", justify="right")
    table.add_column("Detail")
    all_ok = True
    for r in results:
        status = "[green]OK[/green]" if r.ok else "[red]FAIL[/red]"
        if not r.ok:
            all_ok = False
        table.add_row(r.name, status, f"{r.latency_ms:.1f}", r.detail)
    console.print(table)
    log.info("health_check_complete", all_ok=all_ok, services=len(results))
    raise typer.Exit(code=0 if all_ok else 1)


@system_app.command("resources")
def system_resources() -> None:
    """Report memory use vs the 24 GB budget."""
    configure_logging()
    snap = collect_memory_snapshot()
    table = Table(title="fmengine memory budget")
    table.add_column("Bucket")
    table.add_column("Used (GiB)", justify="right")
    table.add_column("Budget (GiB)", justify="right")
    table.add_column("Status")

    rows = [
        ("docker", snap.docker_gb, snap.budget_docker_gb, snap.docker_over_budget),
        ("ollama", snap.ollama_gb, snap.budget_ollama_gb, snap.ollama_over_budget),
        (
            "python_workers",
            snap.python_workers_gb,
            snap.budget_workers_gb,
            snap.workers_over_budget,
        ),
        ("available_headroom", snap.available_gb, snap.budget_headroom_gb, not snap.headroom_ok),
    ]
    for name, used, budget, over in rows:
        status = "[red]BREACH[/red]" if over else "[green]OK[/green]"
        table.add_row(name, f"{used:.2f}", f"{budget:.2f}", status)

    table.add_row("host_total", f"{snap.total_gb:.2f}", f"{snap.budget_total_gb:.2f}", "—")
    table.add_row("host_used", f"{snap.used_gb:.2f}", "—", "—")
    console.print(table)
    overall = "[green]within budget[/green]" if snap.within_budget else "[red]over budget[/red]"
    console.print(f"Overall: {overall}")
    raise typer.Exit(code=0 if snap.within_budget else 1)


@app.command("version")
def version() -> None:
    """Print package version."""
    from fmtrader import __version__

    console.print(__version__)


def main() -> None:
    """Console script entry."""
    app(prog_name="fmtrader")


if __name__ == "__main__":
    main()
