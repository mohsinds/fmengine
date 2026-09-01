"""IBKR paper adapter.

Default: in-process paper simulation with IBKR account metadata (CI-safe).
Live Gateway/TWS: set ``IBKR_GATEWAY_HOST`` + port; real Nautilus IBKR wiring
is the next ops step once paper parity is proven — this module stays the seam.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from fmtrader.core.errors import ExecutionError
from fmtrader.execution.broker.base import (
    AccountState,
    BrokerOrder,
    OrderReport,
    Position,
    ReconcileResult,
)
from fmtrader.execution.broker.paper import PaperBroker
from fmtrader.system.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class IBKRConfig:
    host: str = "127.0.0.1"
    port: int = 7497  # TWS paper default
    account_id: str = "DU000000"
    client_id: int = 1
    mode: str = "paper"  # paper | live

    @classmethod
    def from_env(cls) -> IBKRConfig:
        host = os.environ.get("IBKR_GATEWAY_HOST", "").strip()
        port_s = os.environ.get("IBKR_GATEWAY_PORT", "7497").strip() or "7497"
        acct = (
            os.environ.get("IBKR_PAPER_ACCOUNT_ID", "").strip()
            or os.environ.get("IBKR_ACCOUNT_ID", "").strip()
            or "DU000000"
        )
        return cls(
            host=host or "127.0.0.1",
            port=int(port_s),
            account_id=acct,
            mode="paper",
        )

    @property
    def gateway_configured(self) -> bool:
        return bool(os.environ.get("IBKR_GATEWAY_HOST", "").strip())


class IBKRPaperBroker:
    """IBKR paper venue facade over :class:`PaperBroker` mechanics."""

    name = "ibkr_paper"

    def __init__(
        self,
        config: IBKRConfig | None = None,
        *,
        initial_cash: float = 100_000.0,
        inner: PaperBroker | None = None,
    ) -> None:
        self.config = config or IBKRConfig.from_env()
        self._inner = inner or PaperBroker(initial_cash=initial_cash)
        self._gateway_session: dict[str, Any] | None = None

    @property
    def inner(self) -> PaperBroker:
        return self._inner

    def connect(self) -> None:
        if self.config.gateway_configured:
            self._gateway_session = {
                "host": self.config.host,
                "port": self.config.port,
                "account_id": self.config.account_id,
                "mode": self.config.mode,
            }
            log.info(
                "ibkr_gateway_target_recorded",
                host=self.config.host,
                port=self.config.port,
                account=self.config.account_id,
            )
        self._inner.connect()
        log.info("ibkr_paper_connected", account=self.config.account_id)

    def disconnect(self) -> None:
        self._inner.disconnect()
        self._gateway_session = None

    def force_disconnect(self) -> None:
        self._inner.force_disconnect()
        self._gateway_session = None

    def is_connected(self) -> bool:
        return self._inner.is_connected()

    def subscribe(self, symbol: str) -> None:
        self._inner.subscribe(symbol)

    def subscribed_symbols(self) -> frozenset[str]:
        return self._inner.subscribed_symbols()

    def submit(self, order: BrokerOrder) -> OrderReport:
        return self._inner.submit(order)

    def modify(
        self,
        client_order_id: str,
        *,
        qty: float | None = None,
        limit_price: float | None = None,
    ) -> OrderReport:
        return self._inner.modify(client_order_id, qty=qty, limit_price=limit_price)

    def cancel(self, client_order_id: str) -> OrderReport:
        return self._inner.cancel(client_order_id)

    def cancel_all(self, *, symbol: str | None = None) -> list[OrderReport]:
        return self._inner.cancel_all(symbol=symbol)

    def get_order(self, client_order_id: str) -> OrderReport | None:
        return self._inner.get_order(client_order_id)

    def open_orders(self) -> list[OrderReport]:
        return self._inner.open_orders()

    def positions(self) -> list[Position]:
        return self._inner.positions()

    def account(self) -> AccountState:
        return self._inner.account()

    def reconcile(self) -> ReconcileResult:
        return self._inner.reconcile()

    def set_mark_price(self, symbol: str, price: float) -> None:
        self._inner.set_mark_price(symbol, price)

    def require_live_gateway(self) -> None:
        if not self.config.gateway_configured:
            raise ExecutionError(
                "IBKR Gateway not configured — set IBKR_GATEWAY_HOST (and port/account)"
            )
