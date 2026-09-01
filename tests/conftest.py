"""Pytest fixtures."""

from __future__ import annotations

import polars as pl
import pytest

from tests.helpers import ohlc_frame


@pytest.fixture
def sample_ohlc() -> pl.DataFrame:
    return ohlc_frame(200)
