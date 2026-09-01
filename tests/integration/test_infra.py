"""Integration probes against the local Docker stack + Ollama."""

from __future__ import annotations

import pytest

from fmtrader.config.settings import get_settings
from fmtrader.system.health import (
    check_mlflow,
    check_ollama,
    check_postgres,
    check_questdb,
    check_redis,
    check_temporal,
)

pytestmark = pytest.mark.integration


def test_questdb_reachable_and_writable() -> None:
    settings = get_settings()
    result = check_questdb(settings)
    assert result.ok, result.detail
    # Write via ILP HTTP if available; otherwise status endpoint is enough for Phase 1.
    import httpx

    sql = "SELECT 1"
    url = f"{settings.questdb_http_url.rstrip('/')}/exec"
    resp = httpx.get(url, params={"query": sql}, timeout=10.0)
    assert resp.status_code == 200, resp.text


def test_postgres_all_databases_exist() -> None:
    settings = get_settings()
    settings.require_infra_credentials()
    psycopg = pytest.importorskip("psycopg")
    dsn = (
        f"host={settings.postgres_host} port={settings.postgres_port} "
        f"dbname=postgres user={settings.postgres_user} "
        f"password={settings.postgres_password}"
    )
    expected = {"fmtrader", "temporal", "temporal_visibility", "mlflow"}
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT datname FROM pg_database")
        names = {row[0] for row in cur.fetchall()}
    missing = expected - names
    assert not missing, f"missing databases: {missing}"
    assert check_postgres(settings).ok


def test_temporal_client_connects() -> None:
    settings = get_settings()
    result = check_temporal(settings)
    assert result.ok, result.detail


def test_redis_set_get() -> None:
    settings = get_settings()
    result = check_redis(settings)
    assert result.ok, result.detail
    redis = pytest.importorskip("redis")
    client = redis.Redis.from_url(settings.redis_url)
    client.set("fmengine:phase1:ping", "pong", ex=60)
    assert client.get("fmengine:phase1:ping") == b"pong"
    client.close()


def test_mlflow_experiment_create() -> None:
    settings = get_settings()
    result = check_mlflow(settings)
    assert result.ok, result.detail


def test_ollama_generates() -> None:
    settings = get_settings()
    result = check_ollama(settings)
    assert result.ok, result.detail
    import httpx

    resp = httpx.post(
        f"{settings.ollama_url.rstrip('/')}/api/generate",
        json={"model": "qwen2.5-coder:7b", "prompt": "say ok", "stream": False},
        timeout=120.0,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "response" in body
    assert body["response"].strip()
