"""Memory monitor unit tests."""

from __future__ import annotations

from fmtrader.config.settings import Settings
from fmtrader.system.memory import MemorySnapshot, collect_memory_snapshot


def test_reports_within_budget() -> None:
    settings = Settings(
        questdb_user="u",
        questdb_password="p",
        postgres_user="u",
        postgres_password="p",
        memory_budget_docker_gb=100.0,
        memory_budget_ollama_gb=100.0,
        memory_budget_workers_gb=100.0,
        memory_budget_headroom_gb=0.0,
    )
    snap = collect_memory_snapshot(settings)
    assert isinstance(snap, MemorySnapshot)
    assert snap.total_gb > 0
    assert snap.within_budget is True


def test_flags_breach_when_over_ceiling() -> None:
    snap = MemorySnapshot(
        total_gb=24.0,
        available_gb=1.0,
        used_gb=23.0,
        docker_gb=7.5,
        ollama_gb=0.1,
        python_workers_gb=0.1,
        budget_docker_gb=6.0,
        budget_ollama_gb=8.0,
        budget_workers_gb=6.0,
        budget_headroom_gb=4.0,
        budget_total_gb=24.0,
    )
    assert snap.docker_over_budget is True
    assert snap.headroom_ok is False
    assert snap.within_budget is False
