"""``fmtrader risk`` CLI — kill-switch and limits status."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.json import JSON

from fmtrader.system.logging import configure_logging

risk_app = typer.Typer(help="Risk sizing, limits, and kill-switch.")
console = Console()


@risk_app.command("kill-switch")
def kill_switch_cmd(
    action: str = typer.Argument(..., help="status | engage | clear"),
    reason: str = typer.Option("manual", "--reason"),
    path: Path = typer.Option(Path("data/risk/kill_switch.json"), "--path"),
) -> None:
    """Operate the independent kill-switch."""
    configure_logging()
    from fmtrader.risk.limits import KillSwitch

    ks = KillSwitch(path)
    if action == "status":
        console.print(JSON.from_data(ks.status()))
    elif action == "engage":
        ks.engage(reason=reason)
        console.print(JSON.from_data(ks.status()))
    elif action == "clear":
        ks.clear()
        console.print(JSON.from_data(ks.status()))
    else:
        console.print(f"[red]unknown action {action!r}[/red]")
        raise typer.Exit(code=1)
