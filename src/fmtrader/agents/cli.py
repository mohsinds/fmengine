"""Campaign and worker CLIs."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from fmtrader.system.logging import configure_logging, get_logger

campaign_app = typer.Typer(help="Agentic research campaigns.")
worker_app = typer.Typer(help="Temporal worker for research campaigns.")
console = Console()


@worker_app.command("start")
def worker_start(
    task_queue: str = typer.Option("fmtrader-research", "--task-queue"),
) -> None:
    """Start the Temporal worker (requires --extra orchestration)."""
    configure_logging()
    from fmtrader.orchestration.worker import run_worker

    asyncio.run(run_worker(task_queue=task_queue))


@campaign_app.command("new")
def campaign_new(
    config: Path = typer.Option(..., "--config", exists=True, dir_okay=False),
    local: bool = typer.Option(
        True,
        "--local/--temporal",
        help="Run in-process (default) or start a Temporal workflow",
    ),
    task_queue: str = typer.Option("fmtrader-research", "--task-queue"),
) -> None:
    """Create and start a research campaign."""
    configure_logging()
    log = get_logger("fmtrader.campaign")
    from fmtrader.agents.campaign import CampaignConfig
    from fmtrader.agents.runner import create_campaign, run_campaign_local

    cfg = CampaignConfig.from_yaml(config)
    state = create_campaign(cfg)
    console.print(f"campaign_id={state.campaign_id} status={state.status}")

    if local:
        state = run_campaign_local(state)
        console.print(f"done status={state.status} generations={state.generation}")
        log.info("campaign_local_done", campaign_id=state.campaign_id, status=state.status)
        return

    # Temporal path
    try:
        from temporalio.client import Client
    except ImportError as exc:
        console.print(f"[red]temporalio required for --temporal: {exc}[/red]")
        raise typer.Exit(code=1) from exc

    async def _start() -> str:
        from fmtrader.config.settings import get_settings
        from fmtrader.orchestration.workflow import ResearchCampaignWorkflow

        settings = get_settings()
        client = await Client.connect(f"{settings.temporal_host}:{settings.temporal_port}")
        handle = await client.start_workflow(
            ResearchCampaignWorkflow.run,
            state.to_dict(),
            id=state.campaign_id,
            task_queue=task_queue,
        )
        return str(handle.id)

    wid = asyncio.run(_start())
    console.print(f"temporal workflow started id={wid}")
    log.info("campaign_temporal_started", workflow_id=wid)


@campaign_app.command("status")
def campaign_status(campaign_id: str = typer.Argument(...)) -> None:
    configure_logging()
    from fmtrader.agents.runner import CampaignStore

    state = CampaignStore().load(campaign_id)
    table = Table(title=f"Campaign {campaign_id}")
    table.add_column("Field")
    table.add_column("Value")
    for k in ("status", "generation", "last_error"):
        table.add_row(k, str(getattr(state, k)))
    table.add_row("survivors", str(len(state.survivors)))
    table.add_row("journals", str(len(state.journal_paths)))
    console.print(table)


@campaign_app.command("pause")
def campaign_pause(campaign_id: str = typer.Argument(...)) -> None:
    configure_logging()
    from fmtrader.agents.runner import signal_pause

    state = signal_pause(campaign_id)
    console.print(f"paused campaign_id={campaign_id} status={state.status}")
    # Also signal Temporal if running
    asyncio.run(_signal_temporal(campaign_id, "pause"))


@campaign_app.command("resume")
def campaign_resume(campaign_id: str = typer.Argument(...)) -> None:
    configure_logging()
    from fmtrader.agents.runner import signal_resume

    asyncio.run(_signal_temporal(campaign_id, "resume"))
    state = signal_resume(campaign_id)
    console.print(f"resumed campaign_id={campaign_id} status={state.status}")


@campaign_app.command("abort")
def campaign_abort(campaign_id: str = typer.Argument(...)) -> None:
    configure_logging()
    from fmtrader.agents.runner import signal_abort

    asyncio.run(_signal_temporal(campaign_id, "abort"))
    state = signal_abort(campaign_id)
    console.print(f"aborted campaign_id={campaign_id} status={state.status}")


@campaign_app.command("report")
def campaign_report(campaign_id: str = typer.Argument(...)) -> None:
    configure_logging()
    from fmtrader.agents.journal import ResearchJournal

    md = ResearchJournal().read_report(campaign_id)
    console.print(Markdown(md))


async def _signal_temporal(campaign_id: str, signal: str) -> None:
    try:
        from temporalio.client import Client

        from fmtrader.config.settings import get_settings

        settings = get_settings()
        client = await Client.connect(f"{settings.temporal_host}:{settings.temporal_port}")
        handle = client.get_workflow_handle(campaign_id)
        await handle.signal(signal)
    except Exception:
        pass
