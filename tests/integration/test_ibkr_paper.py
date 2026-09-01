"""IBKR paper integration tests (simulated gateway — no TWS required)."""

from __future__ import annotations

from pathlib import Path

import pytest

from fmtrader.execution.broker.base import BrokerOrder, OrderStatus
from fmtrader.execution.broker.client_ids import make_client_order_id
from fmtrader.execution.broker.ibkr import IBKRConfig, IBKRPaperBroker
from fmtrader.execution.kill_bridge import KillSwitchBridge
from fmtrader.risk.limits import KillSwitch

pytestmark = pytest.mark.integration


def test_connects_and_subscribes() -> None:
    broker = IBKRPaperBroker(IBKRConfig(account_id="DU_TEST"))
    assert not broker.is_connected()
    broker.connect()
    assert broker.is_connected()
    broker.subscribe("GCZ25")
    assert "GCZ25" in broker.subscribed_symbols()
    broker.disconnect()
    assert not broker.is_connected()


def test_order_lifecycle_submit_fill_report() -> None:
    broker = IBKRPaperBroker()
    broker.connect()
    broker.subscribe("MGCZ25")
    broker.set_mark_price("MGCZ25", 2050.5)
    coid = make_client_order_id(
        strategy="ema_cross",
        symbol="MGCZ25",
        signal_key="t0",
        side=1,
        qty=1.0,
    )
    report = broker.submit(BrokerOrder(client_order_id=coid, symbol="MGCZ25", side=1, qty=1.0))
    assert report.status == OrderStatus.FILLED
    assert report.filled_qty == 1.0
    assert report.avg_fill_price == pytest.approx(2050.5)
    assert broker.get_order(coid) is not None
    assert broker.positions()[0].qty == 1.0
    acct = broker.account()
    assert acct.cash < 100_000.0


def test_reconciliation_after_forced_disconnect() -> None:
    broker = IBKRPaperBroker()
    broker.connect()
    broker.subscribe("GCZ25")
    broker.set_mark_price("GCZ25", 2000.0)
    # Working limit order (stays open)
    lim_id = make_client_order_id(
        strategy="ema_cross", symbol="GCZ25", signal_key="limit", side=1, qty=1.0
    )
    lim = broker.submit(
        BrokerOrder(
            client_order_id=lim_id,
            symbol="GCZ25",
            side=1,
            qty=1.0,
            order_type="limit",
            limit_price=1990.0,
        )
    )
    assert lim.status == OrderStatus.SUBMITTED
    assert len(broker.open_orders()) == 1

    # Market fill creates a real position
    mkt_id = make_client_order_id(
        strategy="ema_cross", symbol="GCZ25", signal_key="mkt", side=1, qty=1.0
    )
    broker.submit(BrokerOrder(client_order_id=mkt_id, symbol="GCZ25", side=1, qty=1.0))

    # Phantom local-only position
    broker.inner.inject_phantom_local("FAKE", 3.0)

    broker.force_disconnect()
    assert not broker.is_connected()

    broker.connect()
    result = broker.reconcile()
    assert "FAKE" in result.phantom_symbols
    assert result.open_orders_cancelled >= 1
    assert len(broker.open_orders()) == 0
    # Broker book intact — no phantom on venue
    syms = {p.symbol for p in broker.positions()}
    assert "GCZ25" in syms
    assert "FAKE" not in syms
    # Shadow healed to broker
    assert result.detail in {"healed_to_broker", "matched"} or not result.ok


def test_kill_switch_cancels_open_orders(tmp_path: Path) -> None:
    ks_path = tmp_path / "kill_switch.json"
    ks = KillSwitch(path=ks_path)
    broker = IBKRPaperBroker()
    broker.connect()
    broker.subscribe("GCZ25")
    # Leave a resting limit order
    coid = make_client_order_id(
        strategy="ema_cross", symbol="GCZ25", signal_key="rest", side=-1, qty=1.0
    )
    broker.submit(
        BrokerOrder(
            client_order_id=coid,
            symbol="GCZ25",
            side=-1,
            qty=1.0,
            order_type="limit",
            limit_price=2100.0,
        )
    )
    assert len(broker.open_orders()) == 1

    bridge = KillSwitchBridge(broker, ks, cancel_bound_ms=500.0)
    ks.engage(reason="test_halt", engaged_by="pytest")
    action = bridge.poll()
    assert action is not None
    assert action.engaged
    assert action.cancelled >= 1
    assert action.within_bound
    assert action.elapsed_ms <= action.bound_ms
    assert len(broker.open_orders()) == 0
