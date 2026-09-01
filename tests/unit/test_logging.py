"""Logging correlation-id behaviour."""

from __future__ import annotations

import json
from io import StringIO

import structlog

from fmtrader.system import logging as logging_mod
from fmtrader.system.logging import bind_correlation, get_logger, reset_logging_for_tests


def test_correlation_id_propagates_through_context() -> None:
    reset_logging_for_tests()
    buf = StringIO()

    structlog.configure(
        processors=[
            logging_mod._add_correlation,
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(0),
        logger_factory=structlog.PrintLoggerFactory(file=buf),
        cache_logger_on_first_use=False,
    )
    logging_mod._CONFIGURED = True

    bind_correlation(run_id="run-abc", campaign_id="camp-1")
    log = get_logger("test")
    log.info("hello_correlation")

    raw = buf.getvalue().strip().splitlines()[-1]
    payload = json.loads(raw)
    assert payload["event"] == "hello_correlation"
    assert payload["run_id"] == "run-abc"
    assert payload["campaign_id"] == "camp-1"
