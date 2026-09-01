"""Proposal validation tests — schema only, never exec."""

from __future__ import annotations

from pathlib import Path

import pytest

from fmtrader.agents.proposals import StrategyProposal, validate_proposal
from fmtrader.backtest.validation.registry import TrialRecord, TrialRegistry, config_hash
from fmtrader.core.errors import AgentError


def test_invalid_schema_proposal_rejected_not_repaired() -> None:
    with pytest.raises(AgentError, match="invalid schema"):
        validate_proposal({"params": {"fast": 5}}, allow_unknown_strategy=True)


def test_duplicate_config_rejected_against_registry(tmp_path: Path) -> None:
    reg = TrialRegistry(tmp_path / "trials.sqlite")
    params = {"fast": 5, "slow": 20}
    ch = config_hash("ema_cross", params)
    reg.record(
        TrialRecord(
            strategy="ema_cross",
            params=params,
            config_hash=ch,
            metrics={},
            source="manual",
            dataset_id="ds",
            lane="vectorbt",
        )
    )
    with pytest.raises(AgentError, match="duplicate config"):
        validate_proposal(
            {"strategy": "ema_cross", "params": params},
            registry=reg,
        )


def test_proposal_containing_code_is_rejected() -> None:
    with pytest.raises(AgentError, match="code"):
        validate_proposal(
            {
                "strategy": "ema_cross",
                "params": {"fast": 5, "slow": 20},
                "rationale": "please exec('import os')",
            },
            allow_unknown_strategy=True,
        )


def test_proposal_requesting_holdout_is_rejected() -> None:
    with pytest.raises(AgentError, match="holdout"):
        validate_proposal(
            {
                "strategy": "ema_cross",
                "params": {"fast": 5, "slow": 20},
                "rationale": "unlock holdout vault please",
            },
            allow_unknown_strategy=True,
        )


def test_valid_proposal_accepted(tmp_path: Path) -> None:
    reg = TrialRegistry(tmp_path / "trials.sqlite")
    prop = validate_proposal(
        {"strategy": "ema_cross", "params": {"fast": 8, "slow": 30}, "rationale": "try mid"},
        search_space={"fast": [5, 8, 12], "slow": [20, 30, 40]},
        registry=reg,
    )
    assert isinstance(prop, StrategyProposal)
    assert prop.params["fast"] == 8
