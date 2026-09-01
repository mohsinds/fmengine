"""Futures continuous-series construction seam (pass-through for spot).

Full roll implementation lands in Phase 9 (CME). Spot instruments are a no-op.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

import polars as pl

from fmtrader.core.enums import InstrumentClass
from fmtrader.core.errors import DataError


class AdjustmentMethod(StrEnum):
    """How to stitch successive futures contracts into a continuous series."""

    BACK_ADJUSTED = "back_adjusted"  # Panama / additive
    RATIO_ADJUSTED = "ratio_adjusted"
    UNADJUSTED = "unadjusted"


class RollRule(StrEnum):
    """When to roll from the front contract to the next."""

    VOLUME_CROSSOVER = "volume_crossover"
    OPEN_INTEREST_CROSSOVER = "open_interest_crossover"
    DAYS_BEFORE_EXPIRY = "days_before_expiry"


class ContinuousSeriesBuilder(ABC):
    """Interface for building continuous futures series from raw contracts."""

    @abstractmethod
    def build(
        self,
        raw_by_contract: dict[str, pl.DataFrame],
        *,
        adjustment: AdjustmentMethod,
        roll_rule: RollRule,
        roll_params: dict[str, Any] | None = None,
    ) -> pl.DataFrame:
        """Return a continuous series frame with the same bar columns as raw."""


class PassThroughContinuousSeriesBuilder(ContinuousSeriesBuilder):
    """No-op builder for spot / already-continuous series (e.g. XAUUSD CFD)."""

    def build(
        self,
        raw_by_contract: dict[str, pl.DataFrame],
        *,
        adjustment: AdjustmentMethod,
        roll_rule: RollRule,
        roll_params: dict[str, Any] | None = None,
    ) -> pl.DataFrame:
        if len(raw_by_contract) != 1:
            raise DataError(
                "PassThroughContinuousSeriesBuilder expects exactly one series; "
                f"got {len(raw_by_contract)} — use a real roll builder for multi-contract futures"
            )
        return next(iter(raw_by_contract.values()))


def builder_for(instrument_class: InstrumentClass) -> ContinuousSeriesBuilder:
    """Return the appropriate continuous-series builder for an instrument class."""
    if instrument_class in (
        InstrumentClass.SPOT_CFD,
        InstrumentClass.EQUITY,
        InstrumentClass.CRYPTO,
    ):
        return PassThroughContinuousSeriesBuilder()
    # Futures builders are Phase 9 — expose the seam now.
    raise DataError(
        f"Continuous-series builder for {instrument_class.value} is not implemented yet "
        "(Phase 9 — CME futures onboarding)"
    )
