"""Memory budget monitor against the 24 GB machine ceiling."""

from __future__ import annotations

from dataclasses import dataclass

import psutil

from fmtrader.config.settings import Settings, get_settings


@dataclass(frozen=True)
class MemorySnapshot:
    """Observed memory use vs configured budgets (all values in GiB)."""

    total_gb: float
    available_gb: float
    used_gb: float
    docker_gb: float
    ollama_gb: float
    python_workers_gb: float
    budget_docker_gb: float
    budget_ollama_gb: float
    budget_workers_gb: float
    budget_headroom_gb: float
    budget_total_gb: float

    @property
    def docker_over_budget(self) -> bool:
        return self.docker_gb > self.budget_docker_gb

    @property
    def ollama_over_budget(self) -> bool:
        return self.ollama_gb > self.budget_ollama_gb

    @property
    def workers_over_budget(self) -> bool:
        return self.python_workers_gb > self.budget_workers_gb

    @property
    def headroom_ok(self) -> bool:
        return self.available_gb >= self.budget_headroom_gb

    @property
    def within_budget(self) -> bool:
        return (
            not self.docker_over_budget
            and not self.ollama_over_budget
            and not self.workers_over_budget
            and self.headroom_ok
        )


def _iter_processes(attrs: list[str]):
    """Yield process info; tolerate sandbox / macOS sysctl PermissionError."""
    try:
        iterator = psutil.process_iter(attrs)
    except (psutil.Error, PermissionError, OSError):
        return
    try:
        for proc in iterator:
            yield proc
    except (psutil.Error, PermissionError, OSError):
        return


def _rss_gb_for_name(substr: str) -> float:
    total = 0.0
    needle = substr.lower()
    for proc in _iter_processes(["name", "cmdline", "memory_info"]):
        try:
            name = (proc.info.get("name") or "").lower()
            cmdline = " ".join(proc.info.get("cmdline") or []).lower()
            if needle in name or needle in cmdline:
                mem = proc.info.get("memory_info")
                if mem is not None:
                    total += float(mem.rss) / (1024**3)
        except (psutil.Error, TypeError, ValueError, PermissionError, OSError):
            continue
    return total


def _docker_rss_gb() -> float:
    """Best-effort Docker Desktop + container-related RSS on the host."""
    # Unique PIDs — avoid double-counting overlapping name/cmdline matches.
    seen: set[int] = set()
    total = 0.0
    needles = ("docker", "com.docker", "vpnkit", "qemu-system", "dockerd", "containerd")
    for proc in _iter_processes(["pid", "name", "cmdline", "memory_info"]):
        try:
            pid = int(proc.info["pid"])
            if pid in seen:
                continue
            name = (proc.info.get("name") or "").lower()
            cmdline = " ".join(proc.info.get("cmdline") or []).lower()
            if any(n in name or n in cmdline for n in needles):
                seen.add(pid)
                mem = proc.info.get("memory_info")
                if mem is not None:
                    total += float(mem.rss) / (1024**3)
        except (psutil.Error, TypeError, ValueError, KeyError, PermissionError, OSError):
            continue
    return total


def _ollama_rss_gb() -> float:
    return _rss_gb_for_name("ollama")


def _python_workers_rss_gb() -> float:
    """Approximate Python worker pool usage (excludes Cursor / IDE helpers where possible)."""
    total = 0.0
    for proc in _iter_processes(["name", "cmdline", "memory_info"]):
        try:
            name = (proc.info.get("name") or "").lower()
            cmdline = " ".join(proc.info.get("cmdline") or []).lower()
            if "python" not in name and "python" not in cmdline:
                continue
            if "cursor" in cmdline or "vscode" in cmdline:
                continue
            if "fmtrader" in cmdline or "pytest" in cmdline or "vectorbt" in cmdline:
                mem = proc.info.get("memory_info")
                if mem is not None:
                    total += float(mem.rss) / (1024**3)
        except (psutil.Error, TypeError, ValueError, PermissionError, OSError):
            continue
    return total


def collect_memory_snapshot(settings: Settings | None = None) -> MemorySnapshot:
    """Sample host memory and attribute rough buckets to Docker / Ollama / workers."""
    cfg = settings or get_settings()
    vm = psutil.virtual_memory()
    total_gb = vm.total / (1024**3)
    available_gb = vm.available / (1024**3)
    used_gb = (vm.total - vm.available) / (1024**3)
    # Process attribution can fail under sandboxed API processes — degrade to 0.
    try:
        docker_gb = _docker_rss_gb()
        ollama_gb = _ollama_rss_gb()
        workers_gb = _python_workers_rss_gb()
    except (psutil.Error, PermissionError, OSError):
        docker_gb = ollama_gb = workers_gb = 0.0
    return MemorySnapshot(
        total_gb=total_gb,
        available_gb=available_gb,
        used_gb=used_gb,
        docker_gb=docker_gb,
        ollama_gb=ollama_gb,
        python_workers_gb=workers_gb,
        budget_docker_gb=cfg.memory_budget_docker_gb,
        budget_ollama_gb=cfg.memory_budget_ollama_gb,
        budget_workers_gb=cfg.memory_budget_workers_gb,
        budget_headroom_gb=cfg.memory_budget_headroom_gb,
        budget_total_gb=cfg.memory_budget_total_gb,
    )
