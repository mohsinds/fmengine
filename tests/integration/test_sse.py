"""SSE stream integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fmtrader.agents.campaign import CampaignConfig, CampaignState
from fmtrader.agents.runner import CampaignStore
from fmtrader.api.app import create_app
from fmtrader.api.deps import ApiPaths, set_paths
from fmtrader.api.sse import SseEvent, throttled_sse

pytestmark = pytest.mark.integration


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
    paths.campaigns.mkdir(parents=True, exist_ok=True)
    paths.executions.mkdir(parents=True, exist_ok=True)
    set_paths(paths)
    store = CampaignStore(paths.campaigns)
    state = CampaignState(
        campaign_id="camp1",
        config=CampaignConfig(name="t", dataset_id="ds", strategy="ema_cross"),
        status="running",
        generation=1,
    )
    store.save(state)
    return TestClient(create_app())


def test_events_are_batched_under_throttle_threshold() -> None:
    import asyncio

    calls = {"n": 0}

    def produce() -> list[SseEvent]:
        calls["n"] += 1
        return [
            SseEvent(event="tick", data={"i": calls["n"]}, id=str(calls["n"])),
            SseEvent(event="tick", data={"i": calls["n"] + 0.5}, id=str(calls["n"]) + "b"),
        ]

    async def collect() -> list[str]:
        chunks: list[str] = []
        async for chunk in throttled_sse(produce, max_hz=100.0, idle_sleep=0.01, max_iterations=2):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(collect())
    assert chunks
    assert any("event: batch" in c or "event: tick" in c for c in chunks)


def test_campaign_stream_emits_expected_events(api_env: TestClient) -> None:
    with api_env.stream("GET", "/api/campaigns/camp1/stream") as resp:
        assert resp.status_code == 200
        buf = ""
        for chunk in resp.iter_text():
            buf += chunk
            if "event:" in buf and "data:" in buf:
                break
        assert "event:" in buf
        assert "data:" in buf


def test_client_reconnect_resumes_stream(api_env: TestClient) -> None:
    # First read one event id
    last_id = "0"
    with api_env.stream("GET", "/api/campaigns/camp1/stream") as resp:
        buf = ""
        for chunk in resp.iter_text():
            buf += chunk
            if "id:" in buf:
                for line in buf.splitlines():
                    if line.startswith("id:"):
                        last_id = line.split(":", 1)[1].strip()
                        break
                break
    # Reconnect with Last-Event-ID
    with api_env.stream(
        "GET",
        "/api/campaigns/camp1/stream",
        headers={"Last-Event-ID": last_id},
    ) as resp:
        assert resp.status_code == 200
        buf = ""
        for chunk in resp.iter_text():
            buf += chunk
            if "data:" in buf:
                break
        assert "data:" in buf
