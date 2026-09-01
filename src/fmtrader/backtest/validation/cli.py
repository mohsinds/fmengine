"""``fmtrader validate`` and ``fmtrader registry`` CLIs."""

from __future__ import annotations

from pathlib import Path

import typer
import yaml
from rich.console import Console
from rich.json import JSON
from rich.table import Table

from fmtrader.system.logging import configure_logging, get_logger

validate_app = typer.Typer(help="Validation, walk-forward, and noise calibration.")
registry_app = typer.Typer(help="Trial registry queries and DSR deflation.")
console = Console()


@validate_app.command("run")
def validate_run(
    execution: str = typer.Option(..., "--execution"),
    cv: str = typer.Option("purged", "--cv"),
    folds: int = typer.Option(6, "--folds"),
    embargo: int = typer.Option(60, "--embargo"),
) -> None:
    """Validate an execution with purged CV + DSR/PBO gates."""
    configure_logging()
    _ = cv
    from fmtrader.backtest.validation.service import validate_execution

    out = validate_execution(execution_id=execution, n_folds=folds, embargo=embargo)
    console.print(JSON.from_data(out))


@validate_app.command("walkforward")
def validate_walkforward(
    execution: str = typer.Option(..., "--execution"),
    method: str = typer.Option("rolling", "--method"),
) -> None:
    configure_logging()
    from fmtrader.backtest.costs import CostModelConfig
    from fmtrader.backtest.validation.service import run_walkforward

    cost_path = Path("configs/costs/xauusd_cfd.yaml")
    cfg = CostModelConfig(**yaml.safe_load(cost_path.read_text()))
    out = run_walkforward(
        execution_id=execution,
        method=method,  # type: ignore[arg-type]
        cost_cfg=cfg,
    )
    console.print(JSON.from_data(out))


@validate_app.command("noise-calibration")
def validate_noise_calibration(
    trials: int = typer.Option(1000, "--trials"),
    bars: int = typer.Option(2000, "--bars"),
    seed: int = typer.Option(0, "--seed"),
) -> None:
    """Random-signal sweep that must return NOISE with high PBO."""
    configure_logging()
    log = get_logger("fmtrader.validate")
    from fmtrader.backtest.validation.service import noise_calibration

    gate = noise_calibration(n_trials=trials, n_bars=bars, seed=seed)
    console.print(JSON.from_data(gate.to_dict()))
    log.info("noise_calibration_cli", verdict=gate.verdict, pbo=gate.pbo)
    raise typer.Exit(code=0 if gate.verdict == "NOISE" and gate.pbo > 0.8 else 1)


@registry_app.command("count")
def registry_count(
    strategy: str | None = typer.Option(None, "--strategy"),
) -> None:
    configure_logging()
    from fmtrader.backtest.validation.registry import default_registry

    n = default_registry().count(strategy=strategy)
    console.print(f"trials={n}" + (f" strategy={strategy}" if strategy else ""))


@registry_app.command("deflate")
def registry_deflate(
    strategy: str = typer.Option(..., "--strategy"),
    observed_sharpe: float = typer.Option(..., "--sharpe"),
    n_returns: int = typer.Option(100_000, "--n-returns"),
) -> None:
    configure_logging()
    from fmtrader.backtest.validation.dsr import deflated_sharpe, expected_max_sharpe
    from fmtrader.backtest.validation.registry import default_registry

    n = default_registry().count(strategy=strategy)
    dsr = deflated_sharpe(observed_sharpe, n_trials=max(n, 1), n_returns=n_returns)
    table = Table(title=f"DSR deflation — {strategy}")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("trials", str(n))
    table.add_row("observed_sharpe", f"{observed_sharpe:.4f}")
    table.add_row("expected_max_sharpe", f"{expected_max_sharpe(n_trials=max(n, 1)):.4f}")
    table.add_row("DSR (Φ)", f"{dsr:.4f}")
    console.print(table)
