"""API dependency paths and shared state."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ApiPaths:
    root: Path = field(default_factory=Path.cwd)
    executions: Path = field(default_factory=lambda: Path("data/executions"))
    snapshots: Path = field(default_factory=lambda: Path("data/snapshots"))
    campaigns: Path = field(default_factory=lambda: Path("data/campaigns"))
    registry: Path = field(default_factory=lambda: Path("data/registry/trials.sqlite"))
    vault_audit: Path = field(default_factory=lambda: Path("data/vault/audit.jsonl"))
    promotion_audit: Path = field(
        default_factory=lambda: Path("data/vault/promotion_audit.jsonl")
    )
    kill_switch: Path = field(default_factory=lambda: Path("data/risk/kill_switch.json"))
    settings_file: Path = field(default_factory=lambda: Path("data/api/settings.json"))


_PATHS = ApiPaths()


def get_paths() -> ApiPaths:
    return _PATHS


def set_paths(paths: ApiPaths) -> None:
    global _PATHS
    _PATHS = paths
