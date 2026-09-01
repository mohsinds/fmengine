"""``fmtrader execution`` CLI — provenance + paper broker smoke."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.json import JSON

from fmtrader.system.logging import configure_logging

execution_app = typer.Typer(help="Execution recorder / paper broker.")
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


@execution_app.command("paper-smoke")
def paper_smoke(
    symbol: str = typer.Option("GCZ25", "--symbol"),
    qty: float = typer.Option(1.0, "--qty"),
) -> None:
    """Connect IBKR paper sim, subscribe, market-buy, print account."""
    configure_logging()
    from fmtrader.execution.broker.base import BrokerOrder
    from fmtrader.execution.broker.client_ids import make_client_order_id
    from fmtrader.execution.broker.ibkr import IBKRPaperBroker

    broker = IBKRPaperBroker()
    broker.connect()
    broker.subscribe(symbol)
    broker.set_mark_price(symbol, 2000.0)
    coid = make_client_order_id(
        strategy="smoke",
        symbol=symbol,
        signal_key="cli",
        side=1,
        qty=qty,
    )
    report = broker.submit(BrokerOrder(client_order_id=coid, symbol=symbol, side=1, qty=qty))
    acct = broker.account()
    console.print(
        f"[green]filled[/green] {report.status.value} @ {report.avg_fill_price} "
        f"cash={acct.cash:.2f} equity={acct.equity:.2f}"
    )
    broker.disconnect()
