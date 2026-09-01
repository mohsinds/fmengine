"""Temporal ResearchCampaignWorkflow with pause/resume/abort/adjust_budget signals.

Sandbox-safe: no logging, HTTP, or activity module imports at workflow load time.
Activities are referenced by registered name strings.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

try:
    from temporalio import workflow
    from temporalio.common import RetryPolicy
except ImportError:  # pragma: no cover
    workflow = None  # type: ignore[assignment]
    RetryPolicy = None  # type: ignore[misc, assignment]


if workflow is not None:

    @workflow.defn(name="ResearchCampaignWorkflow")
    class ResearchCampaignWorkflow:
        def __init__(self) -> None:
            self._pause = False
            self._abort = False
            self._budget_override: dict[str, float] | None = None
            self._state: dict[str, Any] = {}

        @workflow.signal
        def pause(self) -> None:
            self._pause = True

        @workflow.signal
        def resume(self) -> None:
            self._pause = False

        @workflow.signal
        def abort(self) -> None:
            self._abort = True

        @workflow.signal
        def adjust_budget(
            self,
            per_campaign_usd: float = 0.0,
            per_day_usd: float = 0.0,
            per_generation_usd: float = 0.0,
        ) -> None:
            self._budget_override = {
                "per_campaign_usd": per_campaign_usd,
                "per_day_usd": per_day_usd,
                "per_generation_usd": per_generation_usd,
            }

        @workflow.query
        def status(self) -> dict[str, Any]:
            return {
                "pause": self._pause,
                "abort": self._abort,
                "state": self._state,
            }

        @workflow.run
        async def run(self, state_dict: dict[str, Any]) -> dict[str, Any]:
            self._state = dict(state_dict)
            max_gen = int(self._state.get("config", {}).get("max_generations", 3))
            retry = RetryPolicy(maximum_attempts=3)

            while int(self._state.get("generation", 0)) < max_gen:
                if self._abort:
                    self._state["abort_requested"] = True
                    self._state["status"] = "aborted"
                    break
                if self._pause:
                    self._state["pause_requested"] = True
                    self._state["status"] = "paused"
                    await workflow.wait_condition(lambda: (not self._pause) or self._abort)
                    if self._abort:
                        self._state["abort_requested"] = True
                        self._state["status"] = "aborted"
                        break
                    self._state["pause_requested"] = False
                    self._pause = False

                if self._budget_override:
                    self._state["budget_override"] = self._budget_override

                self._state = await workflow.execute_activity(
                    "run_generation_activity",
                    self._state,
                    start_to_close_timeout=timedelta(hours=2),
                    heartbeat_timeout=timedelta(minutes=5),
                    retry_policy=retry,
                )
                self._state = await workflow.execute_activity(
                    "checkpoint_activity",
                    self._state,
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=retry,
                )

            if self._state.get("status") not in {"aborted", "paused", "failed"}:
                self._state["status"] = "completed"
                self._state = await workflow.execute_activity(
                    "finalize_campaign_activity",
                    self._state,
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=retry,
                )
            return self._state

else:

    class ResearchCampaignWorkflow:  # type: ignore[no-redef]
        """Placeholder when temporalio is not installed."""

        pass
