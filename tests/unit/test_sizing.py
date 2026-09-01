"""Position sizing unit tests."""

from __future__ import annotations

import pytest

from fmtrader.core.errors import RiskError
from fmtrader.risk.sizing import (
    apply_vol_targeting,
    binary_kelly,
    fractional_kelly,
    vol_target_scale,
)


def test_fractional_kelly_matches_formula() -> None:
    p = 0.6
    full = binary_kelly(p, b=1.0)
    assert abs(full - (2 * p - 1)) < 1e-12
    sized = fractional_kelly(p, b=1.0, fraction=0.25, max_risk_per_trade=1.0, calibrated=True)
    assert abs(sized - 0.25 * full) < 1e-12


def test_kelly_capped_by_max_risk_per_trade() -> None:
    # High edge → full fractional would exceed cap
    sized = fractional_kelly(0.9, b=1.0, fraction=1.0, max_risk_per_trade=0.02, calibrated=True)
    assert sized == pytest.approx(0.02)


def test_kelly_rejects_uncalibrated_probabilities() -> None:
    with pytest.raises(RiskError, match="uncalibrated"):
        fractional_kelly(0.6, calibrated=False)


def test_vol_targeting_scales_inversely_with_realized_vol() -> None:
    s_low = vol_target_scale(0.05, target_vol=0.10)
    s_high = vol_target_scale(0.20, target_vol=0.10)
    assert s_low == pytest.approx(2.0)
    assert s_high == pytest.approx(0.5)
    assert apply_vol_targeting(0.1, 0.20, target_vol=0.10) == pytest.approx(0.05)
    # Higher vol → smaller size
    assert s_high < s_low
