"""ExecutionRecorder — provenance manifest for every backtest run."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fmtrader.core.errors import FeatureError


@dataclass
class ExecutionManifest:
    execution_id: str
    strategy: str
    params: dict[str, Any]
    dataset_id: str
    content_hash: str | None
    lane: str
    cost_multiplier: float
    seed: int
    git_sha: str | None
    started_at: str
    finished_at: str | None = None
    status: str = "running"  # running | complete | failed | incomplete
    failure_point: str | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    funnel: dict[str, Any] = field(default_factory=dict)
    metrics_gross: dict[str, Any] = field(default_factory=dict)
    metrics_net: dict[str, Any] = field(default_factory=dict)
    cost_drag_pct: float | None = None
    trade_count: int = 0
    fragile: bool = False
    cost_sensitivity: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_complete(self) -> bool:
        return self.status == "complete" and self.finished_at is not None

    @property
    def promotable(self) -> bool:
        return self.is_complete and not self.fragile


class ExecutionRecorder:
    """Context manager that writes an append-only execution record."""

    def __init__(self, root: Path, manifest: ExecutionManifest) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest = manifest
        self._path = self.root / f"{manifest.execution_id}.json"
        self._partial_path = self.root / f"{manifest.execution_id}.partial.json"
        self._write(self._partial_path)

    def __enter__(self) -> ExecutionRecorder:
        self.step("start", {"lane": self.manifest.lane})
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: object
    ) -> None:
        if exc_type is not None:
            self.manifest.status = "failed"
            self.manifest.failure_point = (
                self.manifest.steps[-1]["name"] if self.manifest.steps else "unknown"
            )
            self.manifest.finished_at = datetime.now(tz=UTC).isoformat()
            self._write(self._partial_path)
            return
        if self.manifest.status == "running":
            self.manifest.status = "incomplete"
            self.manifest.finished_at = datetime.now(tz=UTC).isoformat()
            self._write(self._partial_path)

    def step(self, name: str, detail: dict[str, Any] | None = None) -> None:
        self.manifest.steps.append(
            {
                "name": name,
                "at": datetime.now(tz=UTC).isoformat(),
                "detail": detail or {},
            }
        )
        # Append-only checkpoint to partial file
        self._write(self._partial_path)

    def complete(self) -> Path:
        self.manifest.status = "complete"
        self.manifest.finished_at = datetime.now(tz=UTC).isoformat()
        self._write(self._path)
        if self._partial_path.exists():
            self._partial_path.unlink()
        return self._path

    def _write(self, path: Path) -> None:
        payload = json.dumps(self.manifest.to_dict(), indent=2, sort_keys=True) + "\n"
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)


def new_execution_id() -> str:
    return uuid.uuid4().hex


def load_execution(path: Path) -> ExecutionManifest:
    data = json.loads(path.read_text(encoding="utf-8"))
    return ExecutionManifest(**data)


def show_execution(root: Path, execution_id: str) -> ExecutionManifest:
    path = root / f"{execution_id}.json"
    partial = root / f"{execution_id}.partial.json"
    if path.exists():
        return load_execution(path)
    if partial.exists():
        man = load_execution(partial)
        if man.status == "running":
            man.status = "incomplete"
        return man
    raise FeatureError(f"Execution not found: {execution_id}")
