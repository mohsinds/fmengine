"""Infrastructure health probes."""

from __future__ import annotations

import importlib.util
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from fmtrader.config.settings import Settings, get_settings


@dataclass(frozen=True)
class HealthCheckResult:
    """Single service probe result."""

    name: str
    ok: bool
    latency_ms: float
    detail: str = ""


def _timed(fn: Callable[[], None]) -> float:
    start = time.perf_counter()
    fn()
    return (time.perf_counter() - start) * 1000.0


def check_questdb(settings: Settings) -> HealthCheckResult:
    # QuestDB 8.x exposes readiness at /ping (204), not /status.
    url = f"{settings.questdb_http_url.rstrip('/')}/ping"
    try:

        def _probe() -> None:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(url)
                if resp.status_code not in (200, 204):
                    raise RuntimeError(f"status {resp.status_code}")

        latency = _timed(_probe)
        return HealthCheckResult("questdb", True, latency, url)
    except Exception as exc:
        return HealthCheckResult("questdb", False, 0.0, f"{url}: {exc}")


def check_postgres(settings: Settings) -> HealthCheckResult:
    if importlib.util.find_spec("psycopg") is None:
        try:

            def _probe() -> None:
                with socket.create_connection(
                    (settings.postgres_host, settings.postgres_port),
                    timeout=5.0,
                ):
                    pass

            latency = _timed(_probe)
            return HealthCheckResult(
                "postgres",
                True,
                latency,
                f"tcp://{settings.postgres_host}:{settings.postgres_port} (no psycopg)",
            )
        except Exception as exc:
            return HealthCheckResult("postgres", False, 0.0, str(exc))

    try:
        import psycopg  # type: ignore[import-not-found]

        settings.require_infra_credentials()
        dsn = (
            f"host={settings.postgres_host} port={settings.postgres_port} "
            f"dbname={settings.postgres_db} user={settings.postgres_user} "
            f"password={settings.postgres_password} connect_timeout=5"
        )

        def _probe() -> None:
            with psycopg.connect(dsn) as conn, conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()

        latency = _timed(_probe)
        return HealthCheckResult("postgres", True, latency, settings.postgres_db)
    except Exception as exc:
        return HealthCheckResult("postgres", False, 0.0, str(exc))


def check_temporal(settings: Settings) -> HealthCheckResult:
    # Temporal gRPC is on 7233; UI HTTP is easier without temporalio installed in core.
    url = settings.temporal_ui_url.rstrip("/")
    try:

        def _probe() -> None:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(url)
                # UI may return 200 or redirect; treat any <500 as up
                if resp.status_code >= 500:
                    raise RuntimeError(f"status {resp.status_code}")

        latency = _timed(_probe)
        return HealthCheckResult("temporal", True, latency, url)
    except Exception as exc:
        return HealthCheckResult("temporal", False, 0.0, f"{url}: {exc}")


def check_redis(settings: Settings) -> HealthCheckResult:
    if importlib.util.find_spec("redis") is None:
        parsed = urlparse(settings.redis_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 6379
        try:

            def _probe() -> None:
                with socket.create_connection((host, port), timeout=5.0) as sock:
                    sock.sendall(b"PING\r\n")
                    data = sock.recv(16)

                if b"PONG" not in data:
                    raise RuntimeError(f"unexpected reply: {data!r}")

            latency = _timed(_probe)
            return HealthCheckResult("redis", True, latency, f"tcp://{host}:{port}")
        except Exception as exc:
            return HealthCheckResult("redis", False, 0.0, str(exc))

    try:
        import redis  # type: ignore[import-not-found]

        def _probe() -> None:
            client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=5)
            if client.ping() is not True:
                raise RuntimeError("PING failed")
            client.close()

        latency = _timed(_probe)
        return HealthCheckResult("redis", True, latency, settings.redis_url)
    except Exception as exc:
        return HealthCheckResult("redis", False, 0.0, str(exc))


def check_mlflow(settings: Settings) -> HealthCheckResult:
    url = f"{settings.mlflow_url.rstrip('/')}/health"
    alt = settings.mlflow_url.rstrip("/")
    try:

        def _probe() -> None:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(url)
                if resp.status_code >= 500:
                    resp = client.get(alt)
                if resp.status_code >= 500:
                    raise RuntimeError(f"status {resp.status_code}")

        latency = _timed(_probe)
        return HealthCheckResult("mlflow", True, latency, url)
    except Exception as exc:
        return HealthCheckResult("mlflow", False, 0.0, f"{url}: {exc}")


def check_ollama(settings: Settings) -> HealthCheckResult:
    url = f"{settings.ollama_url.rstrip('/')}/api/tags"
    try:

        def _probe() -> None:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(url)
                resp.raise_for_status()

        latency = _timed(_probe)
        return HealthCheckResult("ollama", True, latency, url)
    except Exception as exc:
        return HealthCheckResult("ollama", False, 0.0, f"{url}: {exc}")


def run_all_health_checks(settings: Settings | None = None) -> list[HealthCheckResult]:
    """Probe QuestDB, Postgres, Temporal, Redis, MLflow, and Ollama."""
    cfg = settings or get_settings()
    return [
        check_questdb(cfg),
        check_postgres(cfg),
        check_temporal(cfg),
        check_redis(cfg),
        check_mlflow(cfg),
        check_ollama(cfg),
    ]
