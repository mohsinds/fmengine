"""Holdout vault — last ~12 months locked without an unlock token."""

from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from fmtrader.core.errors import HoldoutError


@dataclass(frozen=True)
class HoldoutUnlockToken:
    """Single-use, strategy-scoped unlock token for the holdout vault."""

    token_id: str
    strategy: str
    dataset_id: str
    justification: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HoldoutPolicy:
    """Holdout is the most recent ``months`` ending at dataset end."""

    months: int = 12

    def holdout_start(self, dataset_end: datetime) -> datetime:
        if dataset_end.tzinfo is None:
            dataset_end = dataset_end.replace(tzinfo=UTC)
        # Approximate 12 months as 365 days
        return dataset_end - timedelta(days=30 * self.months)


class HoldoutVault:
    """Filesystem log of unlocks; enforces one unlock per strategy forever."""

    def __init__(self, root: Path = Path("data/holdout")) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.log_path = self.root / "unlocks.jsonl"
        self.consumed_path = self.root / "consumed.json"

    def _consumed(self) -> dict[str, Any]:
        if not self.consumed_path.exists():
            return {}
        data = json.loads(self.consumed_path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        return data

    def _save_consumed(self, data: dict[str, Any]) -> None:
        self.consumed_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")

    def is_consumed(self, strategy: str) -> bool:
        return strategy in self._consumed()

    def issue_token(
        self,
        *,
        strategy: str,
        dataset_id: str,
        justification: str,
    ) -> HoldoutUnlockToken:
        if self.is_consumed(strategy):
            raise HoldoutError(
                f"Holdout already consumed for strategy {strategy!r}; second unlock rejected"
            )
        if not justification.strip():
            raise HoldoutError("Holdout unlock requires a non-empty justification")
        token = HoldoutUnlockToken(
            token_id=secrets.token_hex(16),
            strategy=strategy,
            dataset_id=dataset_id,
            justification=justification.strip(),
            created_at=datetime.now(tz=UTC).isoformat(),
        )
        # Log issue (not yet consumed until used for a read)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"event": "issued", **token.to_dict()}, sort_keys=True) + "\n")
        # Persist pending token
        pending = self.root / f"pending_{strategy}.json"
        pending.write_text(json.dumps(token.to_dict(), indent=2, sort_keys=True) + "\n")
        return token

    def consume(self, token: HoldoutUnlockToken) -> None:
        if self.is_consumed(token.strategy):
            raise HoldoutError(
                f"Holdout already consumed for strategy {token.strategy!r}; second unlock rejected"
            )
        pending = self.root / f"pending_{token.strategy}.json"
        if not pending.exists():
            raise HoldoutError("No pending unlock token for strategy")
        stored = json.loads(pending.read_text(encoding="utf-8"))
        if stored.get("token_id") != token.token_id:
            raise HoldoutError("Unlock token mismatch")
        consumed = self._consumed()
        consumed[token.strategy] = {
            **token.to_dict(),
            "consumed_at": datetime.now(tz=UTC).isoformat(),
        }
        self._save_consumed(consumed)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"event": "consumed", **token.to_dict()}, sort_keys=True) + "\n")
        pending.unlink(missing_ok=True)

    def validate_token(self, token: HoldoutUnlockToken | None, *, strategy: str) -> None:
        if token is None:
            raise HoldoutError("Holdout vault locked: pass HoldoutUnlockToken to read holdout bars")
        if token.strategy != strategy:
            raise HoldoutError("Token strategy mismatch")
        if self.is_consumed(strategy):
            raise HoldoutError(
                f"Holdout already consumed for strategy {strategy!r}; second unlock rejected"
            )


def split_research_holdout(
    frame: pl.DataFrame,
    *,
    policy: HoldoutPolicy | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame, datetime]:
    """Split bars into research (pre-holdout) and holdout frames."""
    policy = policy or HoldoutPolicy()
    if frame.is_empty() or "ts" not in frame.columns:
        return frame, frame.clear(), datetime.now(tz=UTC)
    end = frame["ts"].max()
    assert isinstance(end, datetime)
    start = policy.holdout_start(end)
    research = frame.filter(pl.col("ts") < start)
    holdout = frame.filter(pl.col("ts") >= start)
    return research, holdout, start
