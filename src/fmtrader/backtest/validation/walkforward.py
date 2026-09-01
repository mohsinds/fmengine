"""Walk-forward analysis — rolling and anchored windows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from fmtrader.core.errors import ValidationError


@dataclass(frozen=True)
class WalkForwardWindow:
    window_id: int
    train_idx: np.ndarray
    test_idx: np.ndarray
    method: str


@dataclass
class WalkForwardResult:
    method: str
    windows: list[WalkForwardWindow]
    per_window_metrics: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "n_windows": len(self.windows),
            "per_window_metrics": self.per_window_metrics,
        }


def walk_forward_splits(
    n_samples: int,
    *,
    method: Literal["rolling", "anchored"] = "rolling",
    train_size: int,
    test_size: int,
    step: int | None = None,
) -> list[WalkForwardWindow]:
    """Generate walk-forward train/test index windows.

    Rolling: train window slides forward.
    Anchored: train start stays at 0; train end grows.
    Test sets never overlap.
    """
    if train_size < 1 or test_size < 1:
        raise ValidationError("train_size and test_size must be >= 1")
    step = step or test_size
    if step < 1:
        raise ValidationError("step must be >= 1")

    windows: list[WalkForwardWindow] = []
    wid = 0
    test_start = train_size
    while test_start + test_size <= n_samples:
        test_end = test_start + test_size
        if method == "rolling":
            train_start = test_start - train_size
            train_end = test_start
        elif method == "anchored":
            train_start = 0
            train_end = test_start
        else:
            raise ValidationError(f"Unknown walk-forward method: {method}")
        windows.append(
            WalkForwardWindow(
                window_id=wid,
                train_idx=np.arange(train_start, train_end),
                test_idx=np.arange(test_start, test_end),
                method=method,
            )
        )
        wid += 1
        test_start += step

    if not windows:
        raise ValidationError("No walk-forward windows fit the given sizes")
    return windows


def assert_test_sets_disjoint(windows: list[WalkForwardWindow]) -> None:
    seen: set[int] = set()
    for w in windows:
        for i in w.test_idx.tolist():
            if i in seen:
                raise ValidationError(f"Overlapping test index {i}")
            seen.add(i)
