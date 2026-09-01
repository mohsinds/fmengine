"""Session calendar unit tests (Python + Polars must agree)."""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl

from fmtrader.data.calendars import XAUUSD_FX
from fmtrader.data.quality import _in_session_expr


def test_python_and_polars_session_agree_at_boundaries() -> None:
    samples = [
        datetime(2021, 1, 8, 20, 59, tzinfo=UTC),  # Fri before close — in
        datetime(2021, 1, 8, 21, 0, tzinfo=UTC),  # Fri close — out
        datetime(2021, 1, 8, 21, 30, tzinfo=UTC),  # Fri after close — out
        datetime(2021, 1, 10, 21, 59, tzinfo=UTC),  # Sun before open — out
        datetime(2021, 1, 10, 22, 0, tzinfo=UTC),  # Sun open — in
        datetime(2021, 1, 9, 12, 0, tzinfo=UTC),  # Saturday — out
        datetime(2021, 1, 4, 21, 30, tzinfo=UTC),  # Mon rollover — in (coverage)
        datetime(2021, 1, 1, 12, 0, tzinfo=UTC),  # New Year holiday — out
    ]
    frame = pl.DataFrame({"ts": samples}).with_columns(_in_session_expr(XAUUSD_FX).alias("ins"))
    for ts, ins in zip(samples, frame["ins"].to_list(), strict=True):
        assert XAUUSD_FX.is_in_session(ts) is ins, f"mismatch at {ts}"


def test_friday_after_close_not_tradable() -> None:
    ts = datetime(2021, 1, 8, 21, 0, tzinfo=UTC)
    assert XAUUSD_FX.is_in_session(ts) is False
    df = pl.DataFrame({"ts": [ts]}).with_columns(_in_session_expr(XAUUSD_FX).alias("ins"))
    assert df["ins"][0] is False
