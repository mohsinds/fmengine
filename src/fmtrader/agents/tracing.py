"""LangSmith tracing helpers — no-op when API key absent."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from fmtrader.system.logging import get_logger

log = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def tracing_enabled() -> bool:
    try:
        from fmtrader.config.settings import get_settings

        s = get_settings()
        return bool(s.langsmith_tracing and (s.langsmith_api_key or s.langchain_api_key))
    except Exception:
        return False


def configure_langsmith_env() -> None:
    """Push settings into process env for langsmith SDK (idempotent)."""
    if not tracing_enabled():
        return
    import os

    from fmtrader.config.settings import get_settings

    s = get_settings()
    key = s.langsmith_api_key or s.langchain_api_key
    if key:
        os.environ.setdefault("LANGSMITH_API_KEY", key)
        os.environ.setdefault("LANGCHAIN_API_KEY", key)
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    if s.langsmith_project:
        os.environ.setdefault("LANGSMITH_PROJECT", s.langsmith_project)
        os.environ.setdefault("LANGCHAIN_PROJECT", s.langsmith_project)


def maybe_traceable(name: str, **kwargs: Any) -> Callable[[F], F]:
    """Decorator: langsmith.traceable when configured, else identity."""

    def decorator(fn: F) -> F:
        if not tracing_enabled():
            return fn
        try:
            configure_langsmith_env()
            from langsmith import traceable

            return traceable(name=name, **kwargs)(fn)  # type: ignore[return-value]
        except Exception as exc:
            log.warning("langsmith_traceable_unavailable", error=str(exc))
            return fn

    return decorator


def log_llm_run(
    *,
    name: str,
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> None:
    """Best-effort span for a completed LLM call."""
    if not tracing_enabled():
        return
    try:
        configure_langsmith_env()
        from langsmith import traceable

        @traceable(name=name, run_type="llm", metadata=metadata or {})
        def _inner(prompt: str) -> dict[str, Any]:
            return outputs

        _inner(str(inputs.get("prompt", ""))[:500])
    except Exception as exc:
        log.warning("langsmith_log_failed", error=str(exc))
