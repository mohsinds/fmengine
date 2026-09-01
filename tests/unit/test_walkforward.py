"""Walk-forward unit tests."""

from __future__ import annotations

from fmtrader.backtest.validation.walkforward import (
    assert_test_sets_disjoint,
    walk_forward_splits,
)


def test_rolling_windows_do_not_overlap_test_sets() -> None:
    windows = walk_forward_splits(1000, method="rolling", train_size=200, test_size=50)
    assert_test_sets_disjoint(windows)


def test_anchored_train_set_grows_monotonically() -> None:
    windows = walk_forward_splits(800, method="anchored", train_size=100, test_size=50)
    sizes = [w.train_idx.size for w in windows]
    assert sizes == sorted(sizes)
    assert sizes[0] < sizes[-1]


def test_per_window_metrics_reported() -> None:
    windows = walk_forward_splits(500, method="rolling", train_size=100, test_size=40)
    metrics = [{"window_id": w.window_id, "test_bars": int(w.test_idx.size)} for w in windows]
    assert len(metrics) == len(windows)
    assert all(m["test_bars"] == 40 for m in metrics)
