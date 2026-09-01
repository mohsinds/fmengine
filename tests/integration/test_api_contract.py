"""API contract integration tests — FRONTEND_SPEC §7 / §18."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fmtrader.api.app import create_app
from fmtrader.api.deps import ApiPaths, set_paths
from fmtrader.execution.recorder import ExecutionManifest

pytestmark = pytest.mark.integration

DOCUMENTED_GETS = [
    "/api/campaigns",
    "/api/runs",
    "/api/executions",
    "/api/strategies",
    "/api/registry/trials",
    "/api/registry/counts",
    "/api/datasets",
    "/api/features",
    "/api/vault/status",
    "/api/vault/audit",
    "/api/vault/kill-switch",
    "/api/system/health",
    "/api/system/resources",
    "/api/settings",
]

MANIFEST_KEYS = {
    "execution_id",
    "strategy",
    "params",
    "dataset_id",
    "lane",
    "status",
    "steps",
    "funnel",
    "metrics_gross",
    "metrics_net",
}


@pytest.fixture
def api_env(tmp_path: Path) -> TestClient:
    paths = ApiPaths(
        root=tmp_path,
        executions=tmp_path / "executions",
        snapshots=tmp_path / "snapshots",
        campaigns=tmp_path / "campaigns",
        registry=tmp_path / "registry" / "trials.sqlite",
        vault_audit=tmp_path / "vault" / "audit.jsonl",
        promotion_audit=tmp_path / "vault" / "promotion_audit.jsonl",
        kill_switch=tmp_path / "risk" / "kill_switch.json",
        settings_file=tmp_path / "api" / "settings.json",
    )
    for d in (paths.executions, paths.snapshots, paths.campaigns, paths.registry.parent):
        d.mkdir(parents=True, exist_ok=True)
    set_paths(paths)

    man = ExecutionManifest(
        execution_id="exec_test_1",
        strategy="ema_cross",
        params={"fast": 5, "slow": 20},
        dataset_id="ds_test",
        content_hash="abc",
        lane="vectorbt",
        cost_multiplier=1.0,
        seed=0,
        git_sha="deadbeef",
        started_at="2024-01-01T00:00:00+00:00",
        finished_at="2024-01-01T01:00:00+00:00",
        status="complete",
        steps=[{"name": "start", "at": "2024-01-01T00:00:00+00:00", "detail": {}}],
        funnel={"rawSignals": 10, "ordersFilled": 3, "drops": []},
        metrics_gross={"sharpe": 1.2},
        metrics_net={
            "sharpe": 0.9,
            "dsr": 0.1,
            "pbo": 0.8,
            "verdict": "NOISE",
            "expectancy": 0.5,
            "hit_rate": 0.55,
            "holdout_consumed": False,
        },
        cost_drag_pct=25.0,
        trade_count=40,
        fragile=False,
        cost_sensitivity={"1.5": {"sharpe": -0.1}},
    )
    (paths.executions / "exec_test_1.json").write_text(
        json.dumps(man.to_dict(), indent=2), encoding="utf-8"
    )
    # Dense equity for LTTB
    n = 5000
    equity = {
        "t": list(range(n)),
        "equity": [1.0 + (i / n) * 0.1 for i in range(n)],
    }
    (paths.executions / "exec_test_1.equity.json").write_text(json.dumps(equity), encoding="utf-8")
    for dim in ("session", "hour", "dow", "regime", "exit_reason", "side", "size"):
        (paths.executions / f"exec_test_1.breakdown.{dim}.json").write_text(
            json.dumps(
                {
                    "execution_id": "exec_test_1",
                    "dimension": dim,
                    "buckets": [
                        {
                            "key": "a",
                            "trades": 10,
                            "winRate": 0.5,
                            "expectancyNet": 0.1,
                            "netPnl": 1.0,
                            "sharpe": 0.2,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    return TestClient(create_app())


def test_openapi_schema_valid(api_env: TestClient) -> None:
    r = api_env.get("/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    assert schema.get("openapi")
    assert "/api/executions" in schema["paths"]
    assert "/api/system/health" in schema["paths"]


def test_every_documented_endpoint_responds(api_env: TestClient) -> None:
    for path in DOCUMENTED_GETS:
        r = api_env.get(path)
        assert r.status_code == 200, f"{path} -> {r.status_code}"


def test_execution_manifest_endpoint_returns_all_sections(api_env: TestClient) -> None:
    r = api_env.get("/api/executions/exec_test_1/manifest")
    assert r.status_code == 200
    body = r.json()
    missing = MANIFEST_KEYS - set(body)
    assert not missing, f"missing sections: {missing}"


def test_equity_endpoint_downsamples_to_requested_points(api_env: TestClient) -> None:
    r = api_env.get("/api/executions/exec_test_1/equity", params={"points": 200})
    assert r.status_code == 200
    body = r.json()
    assert body["points"] == 200
    assert len(body["t"]) == 200
    assert len(body["equity"]) == 200


def test_breakdown_endpoint_supports_all_dimensions(api_env: TestClient) -> None:
    for dim in ("session", "hour", "dow", "regime", "exit_reason", "side", "size"):
        r = api_env.get(
            "/api/executions/exec_test_1/breakdown",
            params={"by": dim},
        )
        assert r.status_code == 200, dim
        body = r.json()
        assert body["dimension"] == dim
        assert body["buckets"]


def test_promotion_blocked_when_dsr_fails(api_env: TestClient) -> None:
    r = api_env.post("/api/executions/exec_test_1/promote", json={})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["allowed"] is False
    assert "DSR" in detail["reason"] or detail["verdict"] == "NOISE"
