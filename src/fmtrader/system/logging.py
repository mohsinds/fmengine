"""Structured logging bootstrap (JSON + correlation IDs)."""

from __future__ import annotations

import logging
from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

import structlog

_run_id: ContextVar[str | None] = ContextVar("run_id", default=None)
_campaign_id: ContextVar[str | None] = ContextVar("campaign_id", default=None)

_CONFIGURED = False


def _add_correlation(
    _logger: Any,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    run_id = _run_id.get()
    campaign_id = _campaign_id.get()
    if run_id is not None:
        event_dict.setdefault("run_id", run_id)
    if campaign_id is not None:
        event_dict.setdefault("campaign_id", campaign_id)
    return event_dict


def configure_logging(*, json_logs: bool = True, level: int = logging.INFO) -> None:
    """Configure structlog once per process."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        _add_correlation,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_logs:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.UnicodeDecoder(),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _CONFIGURED = True


def get_logger(name: str | None = None) -> Any:
    """Return a bound structlog logger, ensuring configuration."""
    configure_logging()
    return structlog.get_logger(name)


def bind_correlation(*, run_id: str | None = None, campaign_id: str | None = None) -> None:
    """Bind correlation IDs into contextvars for subsequent log lines."""
    if run_id is not None:
        _run_id.set(run_id)
    if campaign_id is not None:
        _campaign_id.set(campaign_id)


@contextmanager
def correlation_context(
    *,
    run_id: str | None = None,
    campaign_id: str | None = None,
) -> Iterator[None]:
    """Temporarily bind correlation IDs for a block."""
    run_token = _run_id.set(run_id) if run_id is not None else None
    campaign_token = _campaign_id.set(campaign_id) if campaign_id is not None else None
    try:
        yield
    finally:
        if run_token is not None:
            _run_id.reset(run_token)
        if campaign_token is not None:
            _campaign_id.reset(campaign_token)


def reset_logging_for_tests() -> None:
    """Allow reconfiguration in unit tests."""
    global _CONFIGURED
    _CONFIGURED = False
    _run_id.set(None)
    _campaign_id.set(None)
    structlog.reset_defaults()
