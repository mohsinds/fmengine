"""Temporal worker process."""

from __future__ import annotations

from fmtrader.system.logging import configure_logging, get_logger


async def run_worker(*, task_queue: str = "fmtrader-research") -> None:
    configure_logging()
    log = get_logger("fmtrader.worker")
    try:
        from temporalio.client import Client
        from temporalio.worker import Worker
    except ImportError as exc:
        raise SystemExit(
            "temporalio not installed. Run: uv sync --extra orchestration --group dev"
        ) from exc

    from fmtrader.config.settings import get_settings
    from fmtrader.orchestration.activities import temporal_activity_defs
    from fmtrader.orchestration.workflow import ResearchCampaignWorkflow

    settings = get_settings()
    target = f"{settings.temporal_host}:{settings.temporal_port}"
    log.info("worker_connecting", target=target, task_queue=task_queue)
    client = await Client.connect(target)
    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=[ResearchCampaignWorkflow],
        activities=temporal_activity_defs(),
    )
    log.info("worker_started", task_queue=task_queue)
    await worker.run()
