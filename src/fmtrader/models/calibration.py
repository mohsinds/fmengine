"""Probability calibration — Platt (sigmoid) and isotonic (PAVA)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from fmtrader.core.errors import RiskError

CalibratorKind = Literal["platt", "isotonic"]


def brier_score(y_true: NDArray[np.floating], p: NDArray[np.floating]) -> float:
    yt = np.asarray(y_true, dtype=np.float64)
    pp = np.asarray(p, dtype=np.float64)
    if yt.shape != pp.shape:
        raise RiskError("y_true and p must have the same shape")
    return float(np.mean((pp - yt) ** 2))


def _sigmoid(z: NDArray[np.floating]) -> NDArray[np.float64]:
    z = np.clip(np.asarray(z, dtype=np.float64), -500, 500)
    return 1.0 / (1.0 + np.exp(-z))


@dataclass
class PlattCalibrator:
    """Platt scaling: P(y=1|s) = sigmoid(-(A*s + B))."""

    A: float = 1.0
    B: float = 0.0
    fitted: bool = False

    def fit(self, scores: NDArray[np.floating], y: NDArray[np.floating]) -> PlattCalibrator:
        from scipy.optimize import minimize

        s = np.asarray(scores, dtype=np.float64)
        yt = np.asarray(y, dtype=np.float64)
        if s.size != yt.size or s.size < 2:
            raise RiskError("need at least 2 samples to fit Platt calibrator")

        def nll(params: NDArray[np.float64]) -> float:
            a, b = float(params[0]), float(params[1])
            p = _sigmoid(-(a * s + b))
            p = np.clip(p, 1e-12, 1 - 1e-12)
            return float(-np.mean(yt * np.log(p) + (1 - yt) * np.log(1 - p)))

        res = minimize(nll, x0=np.array([1.0, 0.0]), method="L-BFGS-B")
        if not res.success:
            raise RiskError(f"Platt fit failed: {res.message}")
        self.A, self.B = float(res.x[0]), float(res.x[1])
        self.fitted = True
        return self

    def predict(self, scores: NDArray[np.floating]) -> NDArray[np.float64]:
        if not self.fitted:
            raise RiskError("PlattCalibrator not fitted")
        s = np.asarray(scores, dtype=np.float64)
        return _sigmoid(-(self.A * s + self.B))


def _pava(y: NDArray[np.float64], w: NDArray[np.float64] | None = None) -> NDArray[np.float64]:
    """Pool Adjacent Violators — isotonic (non-decreasing) regression."""
    n = int(y.size)
    weights = np.ones(n, dtype=np.float64) if w is None else np.asarray(w, dtype=np.float64)
    vals = [float(v) for v in y]
    wts = [float(v) for v in weights]
    blocks: list[list[int]] = [[i] for i in range(n)]

    i = 0
    while i < len(vals) - 1:
        if vals[i] <= vals[i + 1] + 1e-15:
            i += 1
            continue
        nw = wts[i] + wts[i + 1]
        nv = (vals[i] * wts[i] + vals[i + 1] * wts[i + 1]) / nw
        vals[i] = nv
        wts[i] = nw
        blocks[i] = blocks[i] + blocks[i + 1]
        del vals[i + 1]
        del wts[i + 1]
        del blocks[i + 1]
        if i > 0:
            i -= 1

    out = np.empty(n, dtype=np.float64)
    for v, blk in zip(vals, blocks, strict=True):
        for j in blk:
            out[j] = v
    return out


@dataclass
class IsotonicCalibrator:
    """Isotonic regression calibrator (non-decreasing map from score → probability)."""

    x_: NDArray[np.float64] | None = None
    y_: NDArray[np.float64] | None = None
    fitted: bool = False

    def fit(self, scores: NDArray[np.floating], y: NDArray[np.floating]) -> IsotonicCalibrator:
        s = np.asarray(scores, dtype=np.float64)
        yt = np.asarray(y, dtype=np.float64)
        if s.size != yt.size or s.size < 2:
            raise RiskError("need at least 2 samples to fit isotonic calibrator")
        order = np.argsort(s)
        s_sorted = s[order]
        y_sorted = yt[order]
        fitted_y = _pava(y_sorted)
        self.x_ = s_sorted
        self.y_ = np.clip(fitted_y, 0.0, 1.0)
        self.fitted = True
        return self

    def predict(self, scores: NDArray[np.floating]) -> NDArray[np.float64]:
        if not self.fitted or self.x_ is None or self.y_ is None:
            raise RiskError("IsotonicCalibrator not fitted")
        s = np.asarray(scores, dtype=np.float64)
        out = np.clip(np.interp(s, self.x_, self.y_), 0.0, 1.0)
        return np.asarray(out, dtype=np.float64)


@dataclass
class CalibratedProbability:
    """Wrapper marking probabilities as calibrated for Kelly sizing."""

    values: NDArray[np.float64]
    method: CalibratorKind

    @property
    def calibrated(self) -> bool:
        return True


def calibrate(
    scores: NDArray[np.floating],
    y: NDArray[np.floating],
    *,
    method: CalibratorKind = "isotonic",
) -> tuple[CalibratedProbability, PlattCalibrator | IsotonicCalibrator]:
    if method == "platt":
        cal: PlattCalibrator | IsotonicCalibrator = PlattCalibrator().fit(scores, y)
    elif method == "isotonic":
        cal = IsotonicCalibrator().fit(scores, y)
    else:
        raise RiskError(f"unknown calibrator {method!r}")
    preds = cal.predict(scores)
    return CalibratedProbability(values=preds, method=method), cal


def calibration_curve(
    y_true: NDArray[np.floating],
    p: NDArray[np.floating],
    *,
    n_bins: int = 10,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Return (bin_confidence, bin_accuracy) for reliability diagram."""
    yt = np.asarray(y_true, dtype=np.float64)
    pp = np.asarray(p, dtype=np.float64)
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    confs: list[float] = []
    accs: list[float] = []
    for i in range(n_bins):
        hi = bins[i + 1]
        mask = (pp >= bins[i]) & (pp < hi if i < n_bins - 1 else pp <= hi)
        if not np.any(mask):
            continue
        confs.append(float(np.mean(pp[mask])))
        accs.append(float(np.mean(yt[mask])))
    return np.asarray(confs), np.asarray(accs)
