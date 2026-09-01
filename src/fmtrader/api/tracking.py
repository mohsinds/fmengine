"""Optional MLflow tracking helpers — no-op when mlflow is not installed."""

from __future__ import annotations

from typing import Any

try:
    import mlflow as _mlflow
except ImportError:  # pragma: no cover
    _mlflow = None


def mlflow_available() -> bool:
    return _mlflow is not None


def start_run(*, run_name: str | None = None, tags: dict[str, str] | None = None) -> Any | None:
    if _mlflow is None:
        return None
    return _mlflow.start_run(run_name=run_name, tags=tags)


def log_params(params: dict[str, Any]) -> None:
    if _mlflow is None:
        return
    _mlflow.log_params({k: str(v) for k, v in params.items()})


def log_metrics(metrics: dict[str, float], *, step: int | None = None) -> None:
    if _mlflow is None:
        return
    _mlflow.log_metrics(metrics, step=step)


def end_run() -> None:
    if _mlflow is None:
        return
    _mlflow.end_run()
