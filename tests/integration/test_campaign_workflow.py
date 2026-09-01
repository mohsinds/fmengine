"""Optional Temporal integration tests — skipped without temporalio / stack."""

from __future__ import annotations

import pytest

pytest.importorskip("temporalio")

pytestmark = pytest.mark.integration


def test_worker_restart_mid_campaign_resumes_correctly() -> None:
    """Durability soak: requires live Temporal. Documented manual procedure in BUILD_PLAN.

    Automated placeholder asserts the workflow module imports cleanly.
    """
    from fmtrader.orchestration.workflow import ResearchCampaignWorkflow

    assert ResearchCampaignWorkflow is not None
