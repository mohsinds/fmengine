"""Temporal ResearchCampaignWorkflow with pause/resume/abort/adjust_budget signals.

Sandbox-safe: no logging, HTTP, or activity module imports at workflow load time.
Activities are referenced by registered name strings.

History hygiene:
- Activities take ``campaign_id`` only; full state (leaderboard, spaces) stays on disk.
- ``continue_as_new`` every ``CONTINUE_EVERY`` generations resets history for long soaks.
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


# Generations per continue-as-new window (keeps history well under Temporal limits).
CONTINUE_EVERY = 25


if workflow is not None:

    @workflow.defn(name="ResearchCampaignWorkflow")
    class ResearchCampaignWorkflow:
        def __init__(self) -> None:
            self._pause = False
            self._abort = False
            self._budget_override: dict[str, float] | None = None
            self._snapshot: dict[str, Any] = {}

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
                "snapshot": dict(self._snapshot),
            }

        @workflow.run
        async def run(self, args: dict[str, Any]) -> dict[str, Any]:
            # Accept legacy full state_dict (campaign_id key) or slim {campaign_id: ...}
            campaign_id = str(args.get("campaign_id") or "")
            if not campaign_id:
                raise ValueError("ResearchCampaignWorkflow requires campaign_id")

            self._pause = bool(args.get("pause", False))
            self._abort = bool(args.get("abort", False))
            if isinstance(args.get("budget_override"), dict):
                self._budget_override = dict(args["budget_override"])

            retry = RetryPolicy(maximum_attempts=3)
            act_to = timedelta(hours=2)
            short_to = timedelta(minutes=2)

            self._snapshot = await workflow.execute_activity(
                "load_campaign_snapshot_activity",
                campaign_id,
                start_to_close_timeout=short_to,
                retry_policy=retry,
            )
            max_gen = int(self._snapshot.get("max_generations", 3))
            generation = int(self._snapshot.get("generation", 0))
            gens_this_run = 0

            while generation < max_gen:
                if self._abort:
                    self._snapshot = await workflow.execute_activity(
                        "run_generation_activity",
                        {
                            "campaign_id": campaign_id,
                            "abort_requested": True,
                        },
                        start_to_close_timeout=short_to,
                        retry_policy=retry,
                    )
                    break

                if self._pause:
                    await workflow.wait_condition(lambda: (not self._pause) or self._abort)
                    if self._abort:
                        continue
                    self._pause = False

                payload: dict[str, Any] = {
                    "campaign_id": campaign_id,
                    "pause_requested": False,
                    "abort_requested": False,
                }
                if self._budget_override:
                    payload["budget_override"] = self._budget_override

                self._snapshot = await workflow.execute_activity(
                    "run_generation_activity",
                    payload,
                    start_to_close_timeout=act_to,
                    heartbeat_timeout=timedelta(minutes=5),
                    retry_policy=retry,
                )
                self._snapshot = await workflow.execute_activity(
                    "checkpoint_activity",
                    {"campaign_id": campaign_id},
                    start_to_close_timeout=short_to,
                    retry_policy=retry,
                )

                generation = int(self._snapshot.get("generation", generation))
                status = str(self._snapshot.get("status", "running"))
                gens_this_run += 1

                if status in {"paused", "aborted", "failed"}:
                    break

                if gens_this_run >= CONTINUE_EVERY and generation < max_gen:
                    await workflow.continue_as_new(
                        {
                            "campaign_id": campaign_id,
                            "pause": self._pause,
                            "abort": self._abort,
                            "budget_override": self._budget_override,
                        }
                    )

            status = str(self._snapshot.get("status", "running"))
            if status not in {"aborted", "paused", "failed"}:
                self._snapshot = await workflow.execute_activity(
                    "finalize_campaign_activity",
                    {"campaign_id": campaign_id},
                    start_to_close_timeout=short_to,
                    retry_policy=retry,
                )
            return dict(self._snapshot)

else:

    class ResearchCampaignWorkflow:  # type: ignore[no-redef]
        """Placeholder when temporalio is not installed."""

        pass
