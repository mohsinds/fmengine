"""Optional MLflow tracking helpers — no-op when mlflow is not installed."""

from __future__ import annotations

import os
from typing import Any

try:
    import mlflow as _mlflow
except ImportError:  # pragma: no cover
    _mlflow = None

_configured = False


def mlflow_available() -> bool:
    return _mlflow is not None


def configure_tracking(*, tracking_uri: str | None = None, experiment: str = "fmtrader") -> None:
    """Point the client at the local MLflow server (idempotent)."""
    global _configured
    if _mlflow is None:
        return
    uri = tracking_uri or os.environ.get("MLFLOW_TRACKING_URI") or "http://127.0.0.1:5001"
    _mlflow.set_tracking_uri(uri)
    try:
        _mlflow.set_experiment(experiment)
    except Exception:  # noqa: BLE001 — server may be briefly unavailable
        pass
    _configured = True


def start_run(*, run_name: str | None = None, tags: dict[str, str] | None = None) -> Any | None:
    if _mlflow is None:
        return None
    if not _configured:
        configure_tracking()
    return _mlflow.start_run(run_name=run_name, tags=tags)


def log_params(params: dict[str, Any]) -> None:
    if _mlflow is None:
        return
    safe = {k: str(v)[:250] for k, v in params.items()}
    _mlflow.log_params(safe)


def log_metrics(metrics: dict[str, float], *, step: int | None = None) -> None:
    if _mlflow is None:
        return
    clean: dict[str, float] = {}
    for k, v in metrics.items():
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if fv == fv:  # not NaN
            clean[k] = fv
    if clean:
        _mlflow.log_metrics(clean, step=step)


def end_run() -> None:
    if _mlflow is None:
        return
    _mlflow.end_run()
