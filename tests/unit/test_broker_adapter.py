"""Unit tests for broker adapter idempotency."""

from __future__ import annotations

from fmtrader.execution.broker.base import BrokerOrder, OrderStatus
from fmtrader.execution.broker.client_ids import make_client_order_id
from fmtrader.execution.broker.paper import PaperBroker


def test_client_order_id_is_idempotent() -> None:
    a = make_client_order_id(
        strategy="ema_cross",
        symbol="GCZ25",
        signal_key="2024-01-02T15:00:00+00:00",
        side=1,
        qty=1.0,
    )
    b = make_client_order_id(
        strategy="ema_cross",
        symbol="GCZ25",
        signal_key="2024-01-02T15:00:00+00:00",
        side=1,
        qty=1.0,
    )
    c = make_client_order_id(
        strategy="ema_cross",
        symbol="GCZ25",
        signal_key="2024-01-02T15:01:00+00:00",
        side=1,
        qty=1.0,
    )
    assert a == b
    assert a != c
    assert a.startswith("fm-")


def test_duplicate_submission_does_not_double_fill() -> None:
    broker = PaperBroker(initial_cash=100_000.0)
    broker.connect()
    broker.subscribe("XAUUSD")
    broker.set_mark_price("XAUUSD", 2000.0)
    coid = make_client_order_id(
        strategy="buy_and_hold",
        symbol="XAUUSD",
        signal_key="bar-0",
        side=1,
        qty=2.0,
    )
    order = BrokerOrder(client_order_id=coid, symbol="XAUUSD", side=1, qty=2.0)
    r1 = broker.submit(order)
    r2 = broker.submit(order)
    assert r1.client_order_id == r2.client_order_id
    assert r1.broker_order_id == r2.broker_order_id
    assert r1.status == OrderStatus.FILLED
    assert r2.status == OrderStatus.FILLED
    assert len(broker.fills()) == 1
    pos = broker.positions()
    assert len(pos) == 1
    assert pos[0].qty == 2.0
