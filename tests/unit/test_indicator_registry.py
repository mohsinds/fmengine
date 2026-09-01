"""Indicator registry capability gating."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

import fmtrader.features  # noqa: F401 — register indicators
from fmtrader.core.errors import FeatureError
from fmtrader.features.registry import compute_indicator, get_indicator, validate_against_dataset

# Local helpers (also in tests/conftest.py)
from tests.helpers import ohlc_frame


@dataclass
class Caps:
    has_volume: bool = False
    has_spread: bool = False
    has_open_interest: bool = False


def test_volume_indicator_raises_on_volumeless_dataset() -> None:
    spec = get_indicator("vwap")
    with pytest.raises(FeatureError, match="has_volume"):
        validate_against_dataset(spec, Caps(has_volume=False), dataset_id="xauusd_test")


def test_error_names_dataset_and_missing_capability() -> None:
    with pytest.raises(FeatureError, match="xauusd_1m_bid") as ei:
        compute_indicator(
            "vwap",
            ohlc_frame(50),
            caps=Caps(has_volume=False),
            dataset_id="xauusd_1m_bid_test",
            period=20,
        )
    msg = str(ei.value)
    assert "has_volume=false" in msg
    assert "vwap" in msg


def test_insufficient_lookback_raises() -> None:
    with pytest.raises(FeatureError, match="min_lookback"):
        compute_indicator("sma", ohlc_frame(5), period=20)
