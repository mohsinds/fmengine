"""LLM router unit tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fmtrader.agents.budget import BudgetCaps, BudgetGovernor
from fmtrader.agents.ledger import CostLedger
from fmtrader.agents.llm import LLMRouter, StubLLMClient
from fmtrader.system.memory import MemorySnapshot


def _router(tmp_path: Path, *, sweep_active: bool = False) -> LLMRouter:
    gov = BudgetGovernor(BudgetCaps(), ledger=CostLedger(tmp_path))
    local = StubLLMClient(provider="stub", model="7b", response="local")
    big = StubLLMClient(provider="stub", model="14b", response="big")
    frontier = StubLLMClient(provider="stub", model="frontier", response="front")
    return LLMRouter(
        gov,
        local=local,
        local_14b=big,
        frontier=frontier,
        min_available_gb_for_14b=10.0,
        sweep_active=sweep_active,
    )


def test_falls_back_to_7b_when_memory_below_threshold(tmp_path: Path) -> None:
    r = _router(tmp_path)
    snap = MemorySnapshot(
        total_gb=24,
        available_gb=3.0,
        used_gb=21,
        docker_gb=1,
        ollama_gb=0,
        python_workers_gb=1,
        budget_docker_gb=6,
        budget_ollama_gb=8,
        budget_workers_gb=6,
        budget_headroom_gb=4,
        budget_total_gb=24,
    )
    with patch("fmtrader.agents.llm.collect_memory_snapshot", return_value=snap):
        client = r.select_local_client()
    assert client.model == "7b"


def test_never_loads_14b_during_active_sweep(tmp_path: Path) -> None:
    r = _router(tmp_path, sweep_active=True)
    snap = MemorySnapshot(
        total_gb=24,
        available_gb=20.0,
        used_gb=4,
        docker_gb=1,
        ollama_gb=0,
        python_workers_gb=1,
        budget_docker_gb=6,
        budget_ollama_gb=8,
        budget_workers_gb=6,
        budget_headroom_gb=4,
        budget_total_gb=24,
    )
    with patch("fmtrader.agents.llm.collect_memory_snapshot", return_value=snap):
        client = r.select_local_client()
    assert client.model == "7b"


def test_frontier_tier_only_used_for_gating_nodes(tmp_path: Path) -> None:
    r = _router(tmp_path)
    assert r.select_tier("hypothesize") == "L"
    assert r.select_tier("mutate") == "L"
    assert r.select_tier("critique") == "F"
    assert r.select_tier("select") == "F"
    assert r.select_tier("report") == "F"
