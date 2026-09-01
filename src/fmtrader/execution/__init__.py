"""Execution provenance, broker adapters, and shared paper/live runtime."""

from fmtrader.execution.broker import (
    BrokerAdapter,
    BrokerOrder,
    IBKRPaperBroker,
    PaperBroker,
    make_client_order_id,
)
from fmtrader.execution.kill_bridge import KillSwitchBridge
from fmtrader.execution.runtime import ExecutionRuntime, RuntimeConfig

__all__ = [
    "BrokerAdapter",
    "BrokerOrder",
    "ExecutionRuntime",
    "IBKRPaperBroker",
    "KillSwitchBridge",
    "PaperBroker",
    "RuntimeConfig",
    "make_client_order_id",
]
