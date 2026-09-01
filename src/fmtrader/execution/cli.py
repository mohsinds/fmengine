"""``fmtrader execution`` CLI — inspect execution manifests."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.json import JSON

from fmtrader.system.logging import configure_logging

execution_app = typer.Typer(help="Execution recorder / provenance.")
console = Console()


@execution_app.command("show")
def execution_show(
    execution_id: str = typer.Argument(...),
    root: Path = typer.Option(Path("data/executions"), "--root"),
) -> None:
    """Print manifest, steps, and funnel for an execution."""
    configure_logging()
    from fmtrader.execution.recorder import show_execution

    man = show_execution(root, execution_id)
    console.print(JSON.from_data(man.to_dict()))
    if not man.is_complete:
        console.print(f"[yellow]status={man.status} (not promotable)[/yellow]")
