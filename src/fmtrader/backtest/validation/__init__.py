"""Validation package — purged CV, walk-forward, DSR/PBO, holdout, gates."""

from fmtrader.backtest.validation.gates import GateResult, evaluate_gates
from fmtrader.backtest.validation.holdout import HoldoutUnlockToken, HoldoutVault

__all__ = [
    "GateResult",
    "HoldoutUnlockToken",
    "HoldoutVault",
    "evaluate_gates",
]
