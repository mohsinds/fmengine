"""Backtest orchestration: single run, cost sensitivity, sweeps."""

from __future__ import annotations

import itertools
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from fmtrader.backtest.costs import (
    CostModel,
    CostModelConfig,
    validate_cost_config_for_dataset,
)
from fmtrader.backtest.nautilus.runner import run_nautilus_lane
from fmtrader.backtest.vbt.runner import run_vectorbt_lane
from fmtrader.core.errors import FeatureError
from fmtrader.data.catalog import Catalog, SnapshotManifest
from fmtrader.execution.recorder import ExecutionManifest, ExecutionRecorder, new_execution_id
from fmtrader.strategy.base import get_strategy
from fmtrader.system.logging import get_logger

log = get_logger(__name__)

# Register built-in strategies
from fmtrader.strategy.library import buy_and_hold as _bah  # noqa: E402, F401
from fmtrader.strategy.library import ema_cross as _ema  # noqa: E402, F401


def _record_trial(man: ExecutionManifest, *, source: str = "manual") -> None:
    try:
        from fmtrader.backtest.validation.registry import (
            TrialRecord,
            config_hash,
            default_registry,
        )

        reg = default_registry()
        reg.record(
            TrialRecord(
                strategy=man.strategy,
                params=man.params,
                config_hash=config_hash(man.strategy, man.params),
                metrics=man.metrics_net,
                source=source,  # type: ignore[arg-type]
                dataset_id=man.dataset_id,
                lane=man.lane,
                execution_id=man.execution_id,
            )
        )
    except Exception as exc:
        log.warning("trial_registry_write_failed", error=str(exc))


def _git_sha() -> str | None:
    try:
        import subprocess

        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=Path.cwd(),
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except Exception:
        return None


def load_cost_config(path: Path) -> CostModelConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return CostModelConfig(**data)


def run_backtest(
    *,
    strategy: str,
    params: dict[str, Any],
    dataset_id: str,
    lane: str,
    cost_cfg: CostModelConfig,
    catalog_root: Path = Path("data/catalog"),
    snapshots_dir: Path = Path("data/snapshots"),
    executions_root: Path = Path("data/executions"),
    cost_multiplier: float = 1.0,
    seed: int = 0,
    initial_cash: float = 100_000.0,
    qty: float = 1.0,
    run_sensitivity: bool = True,
    max_bars: int | None = None,
    source: str = "manual",
) -> ExecutionManifest:
    snap = SnapshotManifest.load(snapshots_dir / f"{dataset_id}.json")
    validate_cost_config_for_dataset(cost_cfg, has_spread=snap.has_spread, dataset_id=dataset_id)
    cost = CostModel(cost_cfg.model_copy(update={"multiplier": cost_multiplier}))

    bars = Catalog(catalog_root).read(symbol=snap.symbol, timeframe=snap.timeframe)
    if max_bars is not None and bars.height > max_bars:
        bars = bars.head(max_bars)
    strat = get_strategy(strategy)
    desired = strat.generate(bars, params).to_numpy()

    exec_id = new_execution_id()
    man = ExecutionManifest(
        execution_id=exec_id,
        strategy=strategy,
        params=dict(params),
        dataset_id=dataset_id,
        content_hash=snap.content_hash,
        lane=lane,
        cost_multiplier=cost_multiplier,
        seed=seed,
        git_sha=_git_sha(),
        started_at=datetime.now(tz=UTC).isoformat(),
    )
    with ExecutionRecorder(executions_root, man) as rec:
        rec.step("load_bars", {"rows": bars.height})
        rec.step("generate_signals", {"strategy": strategy})
        if lane == "vectorbt":
            result = run_vectorbt_lane(bars, desired, cost, initial_cash=initial_cash, qty=qty)
        elif lane == "nautilus":
            result = run_nautilus_lane(bars, desired, cost, initial_cash=initial_cash, qty=qty)
        else:
            raise FeatureError(f"Unknown lane {lane!r}")
        rec.step("simulate", {"trades": len(result.trades)})
        man.metrics_net = result.metrics_net.to_dict()
        man.metrics_gross = result.metrics_gross.to_dict()
        man.cost_drag_pct = result.metrics_net.cost_drag_pct
        man.trade_count = result.metrics_net.trade_count
        man.funnel = result.funnel.to_dict()

        if run_sensitivity:
            sens: dict[str, Any] = {}
            for mult in (1.0, 1.5, 2.0):
                c = cost.scaled(mult)
                if lane == "vectorbt":
                    r = run_vectorbt_lane(bars, desired, c, initial_cash=initial_cash, qty=qty)
                else:
                    r = run_nautilus_lane(bars, desired, c, initial_cash=initial_cash, qty=qty)
                sens[f"{mult:.1f}x"] = {
                    "sharpe": r.metrics_net.sharpe,
                    "net_pnl": r.metrics_net.net_pnl,
                    "total_return_net": r.metrics_net.total_return_net,
                }
            man.cost_sensitivity = sens
            # Fragile if edge dies at 1.5x (net sharpe <= 0 while 1.0x was > 0)
            s10 = float(sens["1.0x"]["sharpe"])
            s15 = float(sens["1.5x"]["sharpe"])
            man.fragile = bool(s10 > 0 and s15 <= 0)
            rec.step("cost_sensitivity", {"fragile": man.fragile})

        rec.complete()
    trial_source = source
    if trial_source == "manual" and not run_sensitivity:
        trial_source = "sweep"
    _record_trial(man, source=trial_source)
    log.info(
        "backtest_complete",
        execution_id=exec_id,
        lane=lane,
        net_return=man.metrics_net.get("total_return_net"),
        cost_drag_pct=man.cost_drag_pct,
        fragile=man.fragile,
    )
    return man


def _sweep_one(payload: dict[str, Any]) -> dict[str, Any]:
    """Worker entry for process pool."""
    man = run_backtest(
        strategy=payload["strategy"],
        params=payload["params"],
        dataset_id=payload["dataset_id"],
        lane=payload["lane"],
        cost_cfg=CostModelConfig(**payload["cost_cfg"]),
        catalog_root=Path(payload["catalog_root"]),
        snapshots_dir=Path(payload["snapshots_dir"]),
        executions_root=Path(payload["executions_root"]),
        cost_multiplier=1.0,
        seed=payload.get("seed", 0),
        run_sensitivity=False,
        max_bars=payload.get("max_bars"),
    )
    return {
        "execution_id": man.execution_id,
        "params": man.params,
        "sharpe": man.metrics_net.get("sharpe"),
        "net_pnl": man.metrics_net.get("net_pnl"),
        "cost_drag_pct": man.cost_drag_pct,
        "trade_count": man.trade_count,
    }


def expand_space(space: dict[str, Any], *, max_configs: int) -> list[dict[str, Any]]:
    """Expand a grid search space without materializing unused combos beyond max."""
    grid = space.get("grid") or {}
    keys = sorted(grid.keys())
    values = [list(grid[k]) for k in keys]
    out: list[dict[str, Any]] = []
    for combo in itertools.product(*values):
        cfg = dict(zip(keys, combo, strict=True))
        # EMA-style constraint when both present
        if "fast" in cfg and "slow" in cfg and int(cfg["fast"]) >= int(cfg["slow"]):
            continue
        out.append(cfg)
        if len(out) >= max_configs:
            break
    return out


def run_sweep(
    *,
    strategy: str,
    space_path: Path,
    dataset_id: str,
    cost_cfg: CostModelConfig,
    max_configs: int = 200,
    workers: int | None = None,
    lane: str = "vectorbt",
    catalog_root: Path = Path("data/catalog"),
    snapshots_dir: Path = Path("data/snapshots"),
    executions_root: Path = Path("data/executions"),
    chunk_size: int = 50,
    max_bars: int | None = None,
) -> list[dict[str, Any]]:
    """Chunked parameter sweep with a process pool (default 6 workers)."""
    space = yaml.safe_load(space_path.read_text(encoding="utf-8"))
    configs = expand_space(space, max_configs=max_configs)
    n_workers = workers or int(os.environ.get("FMTRADER_BACKTEST_WORKERS", "6"))
    results: list[dict[str, Any]] = []

    payloads = [
        {
            "strategy": strategy,
            "params": cfg,
            "dataset_id": dataset_id,
            "lane": lane,
            "cost_cfg": cost_cfg.model_dump(),
            "catalog_root": str(catalog_root),
            "snapshots_dir": str(snapshots_dir),
            "executions_root": str(executions_root),
            "seed": i,
            "max_bars": max_bars,
        }
        for i, cfg in enumerate(configs)
    ]

    # Chunk so we never hold the full cartesian product of futures
    for start in range(0, len(payloads), chunk_size):
        chunk = payloads[start : start + chunk_size]
        with ProcessPoolExecutor(max_workers=n_workers) as pool:
            futs = [pool.submit(_sweep_one, p) for p in chunk]
            for fut in as_completed(futs):
                results.append(fut.result())
        log.info("sweep_chunk_done", start=start, size=len(chunk), total=len(results))
    return results
