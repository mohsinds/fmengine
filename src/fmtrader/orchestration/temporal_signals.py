"""Temporal signal bridge used by CLI and HTTP API."""

from __future__ import annotations

import asyncio
from typing import Any


async def signal_temporal_workflow(
    campaign_id: str,
    signal: str,
    *args: Any,
) -> bool:
    """Send pause|resume|abort|adjust_budget to a running Temporal workflow."""
    try:
        from temporalio.client import Client, WorkflowExecutionStatus

        from fmtrader.config.settings import get_settings

        settings = get_settings()
        client = await Client.connect(f"{settings.temporal_host}:{settings.temporal_port}")
        handle = client.get_workflow_handle(campaign_id)
        desc = await handle.describe()
        if desc.status != WorkflowExecutionStatus.RUNNING:
            return False
        if args:
            await handle.signal(signal, *args)
        else:
            await handle.signal(signal)
        return True
    except Exception:
        return False


def signal_temporal_sync(campaign_id: str, signal: str, *args: Any) -> bool:
    try:
        return asyncio.run(signal_temporal_workflow(campaign_id, signal, *args))
    except RuntimeError:
        # Already in an event loop (e.g. some ASGI contexts)
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(signal_temporal_workflow(campaign_id, signal, *args))
        finally:
            loop.close()


async def query_temporal_status(campaign_id: str) -> dict[str, Any] | None:
    try:
        from temporalio.client import Client

        from fmtrader.config.settings import get_settings

        settings = get_settings()
        client = await Client.connect(f"{settings.temporal_host}:{settings.temporal_port}")
        handle = client.get_workflow_handle(campaign_id)
        return await handle.query("status")
    except Exception:
        return None
