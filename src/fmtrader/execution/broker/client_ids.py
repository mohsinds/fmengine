"""Idempotent client order ID generation."""

from __future__ import annotations

import hashlib
from typing import Any


def make_client_order_id(
    *,
    strategy: str,
    symbol: str,
    signal_key: str,
    side: int,
    qty: float,
    intent_seq: int = 0,
) -> str:
    """Deterministic client order id — same inputs → same id (idempotent submit).

    ``signal_key`` is typically the bar timestamp ISO string (or bar index).
    """
    payload = f"{strategy}|{symbol}|{signal_key}|{side}|{qty:.8f}|{intent_seq}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"fm-{digest}"


def parse_client_order_meta(client_order_id: str) -> dict[str, Any]:
    """Return minimal metadata; full payload is not embedded (hash only)."""
    return {"client_order_id": client_order_id, "prefix": "fm"}
