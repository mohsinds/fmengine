"""LLM cost ledger — every call is recorded (SQLite by default)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LedgerEntry:
    campaign_id: str
    generation: int
    provider: str
    model: str
    tier: str
    purpose: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    refused: bool
    refuse_reason: str | None
    created_at: str


class CostLedger:
    """Append-only cost ledger for the budget governor."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path("data/ledger")
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "llm_costs.sqlite"
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS llm_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    tier TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL,
                    completion_tokens INTEGER NOT NULL,
                    cost_usd REAL NOT NULL,
                    refused INTEGER NOT NULL DEFAULT 0,
                    refuse_reason TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_campaign ON llm_calls(campaign_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_day ON llm_calls(created_at)")

    def record(self, entry: LedgerEntry) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO llm_calls (
                    campaign_id, generation, provider, model, tier, purpose,
                    prompt_tokens, completion_tokens, cost_usd, refused, refuse_reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.campaign_id,
                    entry.generation,
                    entry.provider,
                    entry.model,
                    entry.tier,
                    entry.purpose,
                    entry.prompt_tokens,
                    entry.completion_tokens,
                    entry.cost_usd,
                    1 if entry.refused else 0,
                    entry.refuse_reason,
                    entry.created_at,
                ),
            )
            return int(cur.lastrowid or 0)

    def spent_campaign(self, campaign_id: str) -> float:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) AS s FROM llm_calls "
                "WHERE campaign_id = ? AND refused = 0",
                (campaign_id,),
            ).fetchone()
        return float(row["s"])

    def spent_generation(self, campaign_id: str, generation: int) -> float:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) AS s FROM llm_calls "
                "WHERE campaign_id = ? AND generation = ? AND refused = 0",
                (campaign_id, generation),
            ).fetchone()
        return float(row["s"])

    def spent_day(self, day: date | None = None) -> float:
        day = day or datetime.now(tz=UTC).date()
        prefix = day.isoformat()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) AS s FROM llm_calls "
                "WHERE created_at LIKE ? AND refused = 0",
                (f"{prefix}%",),
            ).fetchone()
        return float(row["s"])

    def spent_provider(self, provider: str, *, campaign_id: str | None = None) -> float:
        with self._connect() as conn:
            if campaign_id:
                row = conn.execute(
                    "SELECT COALESCE(SUM(cost_usd), 0) AS s FROM llm_calls "
                    "WHERE provider = ? AND campaign_id = ? AND refused = 0",
                    (provider, campaign_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COALESCE(SUM(cost_usd), 0) AS s FROM llm_calls "
                    "WHERE provider = ? AND refused = 0",
                    (provider,),
                ).fetchone()
        return float(row["s"])

    def count(self, *, campaign_id: str | None = None) -> int:
        with self._connect() as conn:
            if campaign_id:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM llm_calls WHERE campaign_id = ?",
                    (campaign_id,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) AS c FROM llm_calls").fetchone()
        return int(row["c"])

    def list_entries(self, campaign_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM llm_calls WHERE campaign_id = ? ORDER BY id DESC LIMIT ?",
                (campaign_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]
