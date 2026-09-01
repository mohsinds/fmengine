"""Split-conformal prediction intervals for uncertainty gating."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from fmtrader.core.errors import RiskError


@dataclass
class ConformalInterval:
    lower: float
    upper: float
    point: float
    width: float

    @property
    def too_wide(self) -> bool:
        return False  # decided by gate with threshold


@dataclass
class SplitConformalRegressor:
    """Split-conformal intervals around a point predictor.

    Calibration residuals: |y - yhat|. Quantile at level ceil((n+1)*(1-alpha))/n.
    """

    alpha: float = 0.1
    qhat_: float | None = None
    fitted: bool = False

    def fit(
        self,
        y_cal: NDArray[np.floating],
        yhat_cal: NDArray[np.floating],
    ) -> SplitConformalRegressor:
        y = np.asarray(y_cal, dtype=np.float64)
        yh = np.asarray(yhat_cal, dtype=np.float64)
        if y.size != yh.size or y.size < 2:
            raise RiskError("need at least 2 calibration samples for conformal")
        if not (0.0 < self.alpha < 1.0):
            raise RiskError("alpha must be in (0, 1)")
        scores = np.abs(y - yh)
        n = scores.size
        level = int(np.ceil((n + 1) * (1.0 - self.alpha))) / n
        level = min(level, 1.0)
        self.qhat_ = float(np.quantile(scores, level, method="higher"))
        self.fitted = True
        return self

    def predict_interval(self, yhat: float | NDArray[np.floating]) -> list[ConformalInterval]:
        if not self.fitted or self.qhat_ is None:
            raise RiskError("SplitConformalRegressor not fitted")
        arr = np.atleast_1d(np.asarray(yhat, dtype=np.float64))
        out: list[ConformalInterval] = []
        for point in arr:
            lo = float(point - self.qhat_)
            hi = float(point + self.qhat_)
            out.append(ConformalInterval(lower=lo, upper=hi, point=float(point), width=hi - lo))
        return out


@dataclass
class SplitConformalClassifier:
    """Split-conformal for binary probability scores.

    Nonconformity = |y - p|. Interval on probability scale; wide interval ⇒ uncertain.
    """

    alpha: float = 0.1
    qhat_: float | None = None
    fitted: bool = False

    def fit(
        self,
        y_cal: NDArray[np.floating],
        p_cal: NDArray[np.floating],
    ) -> SplitConformalClassifier:
        y = np.asarray(y_cal, dtype=np.float64)
        p = np.asarray(p_cal, dtype=np.float64)
        if y.size != p.size or y.size < 2:
            raise RiskError("need at least 2 calibration samples for conformal")
        scores = np.abs(y - p)
        n = scores.size
        level = min(int(np.ceil((n + 1) * (1.0 - self.alpha))) / n, 1.0)
        self.qhat_ = float(np.quantile(scores, level, method="higher"))
        self.fitted = True
        return self

    def predict_interval(self, p: float | NDArray[np.floating]) -> list[ConformalInterval]:
        if not self.fitted or self.qhat_ is None:
            raise RiskError("SplitConformalClassifier not fitted")
        arr = np.atleast_1d(np.asarray(p, dtype=np.float64))
        out: list[ConformalInterval] = []
        for point in arr:
            lo = float(max(0.0, point - self.qhat_))
            hi = float(min(1.0, point + self.qhat_))
            out.append(ConformalInterval(lower=lo, upper=hi, point=float(point), width=hi - lo))
        return out


def empirical_coverage(
    y_true: NDArray[np.floating],
    intervals: list[ConformalInterval],
) -> float:
    yt = np.asarray(y_true, dtype=np.float64)
    if yt.size != len(intervals):
        raise RiskError("y_true and intervals length mismatch")
    hits = sum(1 for y, iv in zip(yt, intervals, strict=True) if iv.lower <= y <= iv.upper)
    return float(hits / max(len(intervals), 1))
