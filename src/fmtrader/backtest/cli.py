"""``fmtrader backtest`` CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
import yaml
from rich.console import Console
from rich.table import Table

from fmtrader.system.logging import configure_logging, get_logger

backtest_app = typer.Typer(help="Two-lane backtests and parameter sweeps.")
console = Console()


@backtest_app.command("run")
def backtest_run(
    strategy: str = typer.Option(..., "--strategy"),
    params: Path = typer.Option(..., "--params", exists=True, dir_okay=False),
    dataset: str = typer.Option(..., "--dataset"),
    lane: str = typer.Option("vectorbt", "--lane", help="vectorbt | nautilus"),
    cost_config: Path = typer.Option(
        Path("configs/costs/xauusd_cfd.yaml"),
        "--cost-config",
        exists=True,
        dir_okay=False,
    ),
    cost_mult: float = typer.Option(1.0, "--cost-mult"),
    seed: int = typer.Option(0, "--seed"),
    no_sensitivity: bool = typer.Option(False, "--no-sensitivity"),
) -> None:
    """Run a single strategy backtest and write an execution manifest."""
    configure_logging()
    log = get_logger("fmtrader.backtest.cli")
    from fmtrader.backtest.runner import load_cost_config, run_backtest

    raw: dict[str, Any] = yaml.safe_load(params.read_text(encoding="utf-8")) or {}
    param_map = dict(raw.get("params") or raw)
    man = run_backtest(
        strategy=strategy,
        params=param_map,
        dataset_id=dataset,
        lane=lane,
        cost_cfg=load_cost_config(cost_config),
        cost_multiplier=cost_mult,
        seed=seed,
        run_sensitivity=not no_sensitivity,
    )
    console.print(
        f"execution_id={man.execution_id} lane={man.lane} "
        f"net_return={man.metrics_net.get('total_return_net'):.6f} "
        f"cost_drag={man.cost_drag_pct:.2f}% trades={man.trade_count} "
        f"fragile={man.fragile} status={man.status}"
    )
    log.info("cli_backtest_done", execution_id=man.execution_id)


@backtest_app.command("sweep")
def backtest_sweep(
    strategy: str = typer.Option(..., "--strategy"),
    space: Path = typer.Option(..., "--space", exists=True, dir_okay=False),
    dataset: str = typer.Option(..., "--dataset"),
    max_configs: int = typer.Option(200, "--max"),
    workers: int = typer.Option(6, "--workers"),
    lane: str = typer.Option("vectorbt", "--lane"),
    cost_config: Path = typer.Option(
        Path("configs/costs/xauusd_cfd.yaml"),
        "--cost-config",
        exists=True,
        dir_okay=False,
    ),
    max_bars: int | None = typer.Option(
        None,
        "--max-bars",
        help="Optional bar cap for fast sweeps (full dataset when omitted)",
    ),
) -> None:
    """Chunked parameter sweep (default 6 workers)."""
    configure_logging()
    from fmtrader.backtest.runner import load_cost_config, run_sweep

    results = run_sweep(
        strategy=strategy,
        space_path=space,
        dataset_id=dataset,
        cost_cfg=load_cost_config(cost_config),
        max_configs=max_configs,
        workers=workers,
        lane=lane,
        max_bars=max_bars,
    )
    table = Table(title=f"Sweep {strategy} ({len(results)} configs)")
    table.add_column("Sharpe")
    table.add_column("Net PnL")
    table.add_column("Drag %")
    table.add_column("Trades")
    table.add_column("Params")
    for r in sorted(results, key=lambda x: float(x.get("sharpe") or -999), reverse=True)[:20]:
        table.add_row(
            f"{r.get('sharpe'):.3f}",
            f"{r.get('net_pnl'):.2f}",
            f"{r.get('cost_drag_pct'):.1f}",
            str(r.get("trade_count")),
            str(r.get("params")),
        )
    console.print(table)
