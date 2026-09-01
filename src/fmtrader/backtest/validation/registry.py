"""Trial registry — every evaluated configuration (multiple-testing denominator)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fmtrader.core.errors import ValidationError


def config_hash(strategy: str, params: dict[str, Any]) -> str:
    blob = json.dumps(
        {"strategy": strategy, "params": params}, sort_keys=True, separators=(",", ":")
    )
    return "sha256:" + hashlib.sha256(blob.encode()).hexdigest()


@dataclass
class TrialRecord:
    strategy: str
    params: dict[str, Any]
    config_hash: str
    metrics: dict[str, Any]
    source: Literal["manual", "agent", "sweep", "noise_calibration"]
    dataset_id: str
    lane: str
    execution_id: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TrialRegistry:
    """SQLite-backed registry (Postgres DSN optional later via same SQL subset)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trials (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    config_hash TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    dataset_id TEXT NOT NULL,
                    lane TEXT NOT NULL,
                    execution_id TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trials_strategy ON trials(strategy)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trials_hash ON trials(config_hash)")

    def record(self, trial: TrialRecord) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO trials (
                    strategy, params_json, config_hash, metrics_json,
                    source, dataset_id, lane, execution_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trial.strategy,
                    json.dumps(trial.params, sort_keys=True),
                    trial.config_hash,
                    json.dumps(trial.metrics, sort_keys=True),
                    trial.source,
                    trial.dataset_id,
                    trial.lane,
                    trial.execution_id,
                    trial.created_at,
                ),
            )
            return int(cur.lastrowid or 0)

    def has_config(self, config_hash_value: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM trials WHERE config_hash = ? LIMIT 1",
                (config_hash_value,),
            ).fetchone()
            return row is not None

    def count(self, *, strategy: str | None = None) -> int:
        with self._connect() as conn:
            if strategy is None:
                row = conn.execute("SELECT COUNT(*) AS n FROM trials").fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM trials WHERE strategy = ?",
                    (strategy,),
                ).fetchone()
            return int(row["n"])

    def list_trials(self, *, strategy: str | None = None) -> list[TrialRecord]:
        with self._connect() as conn:
            if strategy is None:
                rows = conn.execute("SELECT * FROM trials ORDER BY id").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM trials WHERE strategy = ? ORDER BY id",
                    (strategy,),
                ).fetchall()
        out: list[TrialRecord] = []
        for r in rows:
            out.append(
                TrialRecord(
                    strategy=r["strategy"],
                    params=json.loads(r["params_json"]),
                    config_hash=r["config_hash"],
                    metrics=json.loads(r["metrics_json"]),
                    source=r["source"],
                    dataset_id=r["dataset_id"],
                    lane=r["lane"],
                    execution_id=r["execution_id"],
                    created_at=r["created_at"],
                )
            )
        return out

    def require_written(self, config_hash_value: str) -> None:
        if not self.has_config(config_hash_value):
            raise ValidationError(f"Config not in trial registry: {config_hash_value}")


def default_registry(root: Path = Path("data/registry")) -> TrialRegistry:
    return TrialRegistry(root / "trials.sqlite")
