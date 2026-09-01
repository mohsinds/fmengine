"""Unit tests for LTTB and promotion gate."""

from __future__ import annotations

from fmtrader.api.lttb import lttb
from fmtrader.api.promotion import promotion_decision
from fmtrader.execution.recorder import ExecutionManifest


def test_lttb_reduces_points() -> None:
    xs = list(range(10_000))
    ys = [float(i % 50) for i in xs]
    dx, dy = lttb(xs, ys, 500)
    assert len(dx) == 500
    assert len(dy) == 500
    assert dx[0] == 0
    assert dx[-1] == 9999


def test_promotion_blocks_low_dsr() -> None:
    man = ExecutionManifest(
        execution_id="x",
        strategy="ema_cross",
        params={},
        dataset_id="d",
        content_hash=None,
        lane="vectorbt",
        cost_multiplier=1.0,
        seed=0,
        git_sha=None,
        started_at="t0",
        finished_at="t1",
        status="complete",
        metrics_net={"sharpe": 2.0, "dsr": 0.1, "pbo": 0.9},
        trade_count=50,
        fragile=False,
    )
    d = promotion_decision(man, min_dsr=0.5)
    assert d.allowed is False
    assert d.verdict == "NOISE"
