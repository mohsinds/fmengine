"""Config-driven trading cost model (spread, commission, slippage)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from fmtrader.core.errors import FeatureError


class CostModelConfig(BaseModel):
    """Per-instrument cost assumptions.

    When the dataset has ``has_spread=false``, ``spread_abs`` must be > 0 —
    zero (or missing) spread is rejected to prevent silent free trading.
    """

    spread_abs: float = Field(
        ...,
        description="Absolute price spread (ask-bid). Required when unmeasured.",
    )
    commission_per_side: float = Field(default=0.0, ge=0.0)
    commission_bps: float = Field(default=0.0, ge=0.0)
    slippage_base_abs: float = Field(default=0.0, ge=0.0)
    slippage_vol_mult: float = Field(
        default=0.0,
        ge=0.0,
        description="Extra slippage = mult * ATR (or realized vol proxy) in price units",
    )
    offsession_spread_mult: float = Field(default=1.5, ge=1.0)
    order_type: Literal["market", "limit"] = "market"
    limit_slippage_factor: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="Limit orders pay this fraction of market slippage",
    )
    funding_bps_per_day: float = Field(default=0.0, ge=0.0)
    multiplier: float = Field(default=1.0, gt=0.0, description="Cost sensitivity 1.0/1.5/2.0")

    @model_validator(mode="after")
    def _spread_positive(self) -> CostModelConfig:
        if self.spread_abs < 0:
            raise ValueError("spread_abs must be >= 0")
        return self


def validate_cost_config_for_dataset(
    cfg: CostModelConfig,
    *,
    has_spread: bool,
    dataset_id: str,
) -> None:
    """Reject zero/assumed-free costs on unmeasured-spread datasets."""
    if not has_spread and cfg.spread_abs <= 0:
        raise FeatureError(
            f"Cost model spread_abs must be > 0 for dataset {dataset_id!r} "
            f"with has_spread=false (refusing silent zero-spread trading)"
        )


@dataclass(frozen=True)
class FillCost:
    """Cost components for one fill (one side)."""

    spread_half: float
    slippage: float
    commission: float

    @property
    def total(self) -> float:
        return self.spread_half + self.slippage + self.commission


class CostModel:
    """Apply spread/commission/slippage around mid/close for fills."""

    def __init__(self, cfg: CostModelConfig) -> None:
        self.cfg = cfg

    def scaled(self, multiplier: float) -> CostModel:
        return CostModel(self.cfg.model_copy(update={"multiplier": float(multiplier)}))

    def one_way(
        self,
        *,
        price: float,
        side: Literal["buy", "sell"],
        vol_proxy: float = 0.0,
        in_session: bool = True,
        size: float = 1.0,
    ) -> tuple[float, FillCost]:
        """Return (fill_price, cost breakdown).

        Buy pays mid + half-spread + slippage; sell receives mid - half-spread - slippage.
        Commission is cash, not in the price (tracked separately for P&L).
        """
        m = self.cfg.multiplier
        spread = self.cfg.spread_abs * m
        if not in_session:
            spread *= self.cfg.offsession_spread_mult
        half = 0.5 * spread
        slip = (self.cfg.slippage_base_abs + self.cfg.slippage_vol_mult * max(vol_proxy, 0.0)) * m
        if self.cfg.order_type == "limit":
            slip *= self.cfg.limit_slippage_factor
        commission = (
            self.cfg.commission_per_side + price * self.cfg.commission_bps * 1e-4 * abs(size)
        ) * m
        fill = price + half + slip if side == "buy" else price - half - slip
        return fill, FillCost(spread_half=half, slippage=slip, commission=commission)

    def round_trip_cost_abs(
        self, *, price: float, vol_proxy: float = 0.0, in_session: bool = True
    ) -> float:
        """Approximate all-in one-unit round-trip cost in price units (excl. commission cash)."""
        _, b = self.one_way(price=price, side="buy", vol_proxy=vol_proxy, in_session=in_session)
        _, s = self.one_way(price=price, side="sell", vol_proxy=vol_proxy, in_session=in_session)
        return b.spread_half + b.slippage + s.spread_half + s.slippage + b.commission + s.commission
