"""Broker adapter types and protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, Protocol, runtime_checkable

Side = Literal[-1, 0, 1]
OrderType = Literal["market", "limit"]


class OrderStatus(StrEnum):
    NEW = "new"
    SUBMITTED = "submitted"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass(frozen=True)
class BrokerOrder:
    """Venue order with client-generated idempotency key."""

    client_order_id: str
    symbol: str
    side: Side  # +1 buy / -1 sell (to flatten or reverse)
    qty: float
    order_type: OrderType = "market"
    limit_price: float | None = None
    strategy: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class OrderReport:
    client_order_id: str
    broker_order_id: str
    status: OrderStatus
    symbol: str
    side: Side
    qty: float
    filled_qty: float = 0.0
    avg_fill_price: float | None = None
    submitted_at: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())
    reject_reason: str | None = None


@dataclass(frozen=True)
class FillReport:
    client_order_id: str
    broker_order_id: str
    symbol: str
    side: Side
    qty: float
    price: float
    ts: str


@dataclass
class Position:
    symbol: str
    qty: float
    avg_price: float


@dataclass
class AccountState:
    cash: float
    equity: float
    buying_power: float
    currency: str = "USD"


@dataclass
class ReconcileResult:
    """Outcome of reconciling local intent vs broker state after reconnect."""

    ok: bool
    local_positions: dict[str, float]
    broker_positions: dict[str, float]
    phantom_symbols: list[str]
    missing_symbols: list[str]
    open_orders_cancelled: int = 0
    detail: str = ""


@runtime_checkable
class BrokerAdapter(Protocol):
    """Venue boundary — strategies never call this; execution runtime does."""

    name: str

    def connect(self) -> None: ...

    def disconnect(self) -> None: ...

    def is_connected(self) -> bool: ...

    def subscribe(self, symbol: str) -> None: ...

    def subscribed_symbols(self) -> frozenset[str]: ...

    def submit(self, order: BrokerOrder) -> OrderReport: ...

    def modify(
        self,
        client_order_id: str,
        *,
        qty: float | None = None,
        limit_price: float | None = None,
    ) -> OrderReport: ...

    def cancel(self, client_order_id: str) -> OrderReport: ...

    def cancel_all(self, *, symbol: str | None = None) -> list[OrderReport]: ...

    def get_order(self, client_order_id: str) -> OrderReport | None: ...

    def open_orders(self) -> list[OrderReport]: ...

    def positions(self) -> list[Position]: ...

    def account(self) -> AccountState: ...

    def reconcile(self) -> ReconcileResult: ...

    def set_mark_price(self, symbol: str, price: float) -> None:
        """Update last price used for market fills (paper / sim)."""
        ...
