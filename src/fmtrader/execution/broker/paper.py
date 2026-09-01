"""In-memory paper broker — same interface as live venues."""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime

from fmtrader.core.errors import ExecutionError
from fmtrader.execution.broker.base import (
    AccountState,
    BrokerOrder,
    FillReport,
    OrderReport,
    OrderStatus,
    Position,
    ReconcileResult,
)
from fmtrader.system.logging import get_logger

log = get_logger(__name__)


class PaperBroker:
    """Deterministic paper venue with idempotent submits and reconcile."""

    name = "paper"

    def __init__(self, *, initial_cash: float = 100_000.0, currency: str = "USD") -> None:
        self._cash = initial_cash
        self._currency = currency
        self._connected = False
        self._subscribed: set[str] = set()
        self._marks: dict[str, float] = {}
        self._orders: dict[str, OrderReport] = {}
        self._fills: list[FillReport] = []
        self._positions: dict[str, Position] = {}
        # Local shadow book used for reconcile after reconnect
        self._local_shadow: dict[str, float] = {}
        self._lock = threading.RLock()
        self._forced_disconnect = False

    def connect(self) -> None:
        with self._lock:
            self._connected = True
            # Do not clear _forced_disconnect here — reconcile() consumes it.
            log.info("paper_broker_connected")

    def disconnect(self) -> None:
        with self._lock:
            self._connected = False
            log.info("paper_broker_disconnected")

    def force_disconnect(self) -> None:
        """Simulate a dropped session without clearing broker state."""
        with self._lock:
            self._connected = False
            self._forced_disconnect = True
            log.warning("paper_broker_forced_disconnect")

    def is_connected(self) -> bool:
        return self._connected

    def subscribe(self, symbol: str) -> None:
        self._require_connected()
        with self._lock:
            self._subscribed.add(symbol)

    def subscribed_symbols(self) -> frozenset[str]:
        return frozenset(self._subscribed)

    def set_mark_price(self, symbol: str, price: float) -> None:
        with self._lock:
            self._marks[symbol] = float(price)

    def submit(self, order: BrokerOrder) -> OrderReport:
        self._require_connected()
        with self._lock:
            existing = self._orders.get(order.client_order_id)
            if existing is not None:
                # Idempotent: return prior report; do not fill again
                log.info(
                    "paper_submit_idempotent",
                    client_order_id=order.client_order_id,
                    status=existing.status.value,
                )
                return existing

            if order.symbol not in self._subscribed:
                raise ExecutionError(f"Not subscribed to {order.symbol}")
            if order.qty <= 0:
                raise ExecutionError("qty must be positive")
            if order.side == 0:
                raise ExecutionError("side must be +1 or -1")

            broker_id = f"pb-{uuid.uuid4().hex[:12]}"
            now = datetime.now(tz=UTC).isoformat()
            report = OrderReport(
                client_order_id=order.client_order_id,
                broker_order_id=broker_id,
                status=OrderStatus.SUBMITTED,
                symbol=order.symbol,
                side=order.side,
                qty=order.qty,
                submitted_at=now,
                updated_at=now,
            )
            self._orders[order.client_order_id] = report

            if order.order_type == "market":
                self._fill_market(order, report)
            # Limit orders stay open until cancelled or later filled by runtime
            return self._orders[order.client_order_id]

    def modify(
        self,
        client_order_id: str,
        *,
        qty: float | None = None,
        limit_price: float | None = None,
    ) -> OrderReport:
        self._require_connected()
        with self._lock:
            report = self._orders.get(client_order_id)
            if report is None:
                raise ExecutionError(f"Unknown order {client_order_id}")
            if report.status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED):
                raise ExecutionError(f"Cannot modify order in status {report.status}")
            if qty is not None:
                report.qty = float(qty)
            report.updated_at = datetime.now(tz=UTC).isoformat()
            _ = limit_price  # paper market path ignores limit for now
            return report

    def cancel(self, client_order_id: str) -> OrderReport:
        self._require_connected()
        with self._lock:
            report = self._orders.get(client_order_id)
            if report is None:
                raise ExecutionError(f"Unknown order {client_order_id}")
            if report.status == OrderStatus.FILLED:
                return report
            report.status = OrderStatus.CANCELLED
            report.updated_at = datetime.now(tz=UTC).isoformat()
            return report

    def cancel_all(self, *, symbol: str | None = None) -> list[OrderReport]:
        self._require_connected()
        with self._lock:
            out: list[OrderReport] = []
            for report in self._orders.values():
                if report.status not in (
                    OrderStatus.SUBMITTED,
                    OrderStatus.PARTIAL,
                    OrderStatus.NEW,
                ):
                    continue
                if symbol is not None and report.symbol != symbol:
                    continue
                report.status = OrderStatus.CANCELLED
                report.updated_at = datetime.now(tz=UTC).isoformat()
                out.append(report)
            log.warning("paper_cancel_all", cancelled=len(out), symbol=symbol)
            return out

    def get_order(self, client_order_id: str) -> OrderReport | None:
        return self._orders.get(client_order_id)

    def open_orders(self) -> list[OrderReport]:
        return [
            o
            for o in self._orders.values()
            if o.status in (OrderStatus.NEW, OrderStatus.SUBMITTED, OrderStatus.PARTIAL)
        ]

    def positions(self) -> list[Position]:
        return [p for p in self._positions.values() if abs(p.qty) > 1e-12]

    def account(self) -> AccountState:
        with self._lock:
            equity = self._cash
            for sym, pos in self._positions.items():
                mark = self._marks.get(sym, pos.avg_price)
                equity += pos.qty * mark
            return AccountState(
                cash=self._cash,
                equity=equity,
                buying_power=self._cash,
                currency=self._currency,
            )

    def reconcile(self) -> ReconcileResult:
        """Compare shadow local book to broker positions; clear phantoms."""
        self._require_connected()
        with self._lock:
            broker = {p.symbol: p.qty for p in self.positions()}
            local = dict(self._local_shadow)
            phantoms = [
                s for s, q in local.items() if abs(q) > 1e-12 and abs(broker.get(s, 0.0)) < 1e-12
            ]
            missing = [
                s for s, q in broker.items() if abs(q) > 1e-12 and abs(local.get(s, 0.0)) < 1e-12
            ]
            # Heal: adopt broker as source of truth
            self._local_shadow = dict(broker)
            cancelled = 0
            if self._forced_disconnect:
                # After forced disconnect, cancel stale working limit orders
                cancelled = len(self.cancel_all())
                self._forced_disconnect = False
            ok = len(phantoms) == 0
            return ReconcileResult(
                ok=ok,
                local_positions=local,
                broker_positions=broker,
                phantom_symbols=phantoms,
                missing_symbols=missing,
                open_orders_cancelled=cancelled,
                detail="healed_to_broker" if not ok else "matched",
            )

    def sync_local_shadow(self) -> None:
        """Call after fills so local matches broker (normal path)."""
        with self._lock:
            self._local_shadow = {p.symbol: p.qty for p in self.positions()}

    def inject_phantom_local(self, symbol: str, qty: float) -> None:
        """Test helper: create a local-only phantom position."""
        with self._lock:
            self._local_shadow[symbol] = qty

    def fills(self) -> list[FillReport]:
        return list(self._fills)

    def _fill_market(self, order: BrokerOrder, report: OrderReport) -> None:
        price = self._marks.get(order.symbol)
        if price is None:
            report.status = OrderStatus.REJECTED
            report.reject_reason = "no_mark_price"
            report.updated_at = datetime.now(tz=UTC).isoformat()
            return
        signed_qty = order.qty if order.side > 0 else -order.qty
        self._apply_fill(order.symbol, signed_qty, price)
        report.status = OrderStatus.FILLED
        report.filled_qty = order.qty
        report.avg_fill_price = price
        report.updated_at = datetime.now(tz=UTC).isoformat()
        self._fills.append(
            FillReport(
                client_order_id=order.client_order_id,
                broker_order_id=report.broker_order_id,
                symbol=order.symbol,
                side=order.side,
                qty=order.qty,
                price=price,
                ts=report.updated_at,
            )
        )
        self.sync_local_shadow()

    def _apply_fill(self, symbol: str, signed_qty: float, price: float) -> None:
        self._cash -= signed_qty * price
        pos = self._positions.get(symbol)
        if pos is None:
            self._positions[symbol] = Position(symbol=symbol, qty=signed_qty, avg_price=price)
            return
        new_qty = pos.qty + signed_qty
        if abs(new_qty) < 1e-12:
            del self._positions[symbol]
            return
        if pos.qty * signed_qty > 0:
            # Add to same side — VWAP
            pos.avg_price = (pos.avg_price * pos.qty + price * signed_qty) / new_qty
            pos.qty = new_qty
            return
        # Reduce or flip
        if abs(signed_qty) < abs(pos.qty):
            pos.qty = new_qty
        else:
            pos.qty = new_qty
            pos.avg_price = price

    def _require_connected(self) -> None:
        if not self._connected:
            raise ExecutionError("Broker not connected")
