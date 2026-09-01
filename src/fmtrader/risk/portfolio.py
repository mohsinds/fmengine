"""Portfolio construction seam — RMT / Ledoit-Wolf deferred to multi-asset phase."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from fmtrader.core.errors import RiskError


@dataclass
class PortfolioConfig:
    method: str = "identity"  # future: "ledoit_wolf", "rmt"


def clean_covariance(
    sample_cov: NDArray[np.floating],
    *,
    config: PortfolioConfig | None = None,
) -> NDArray[np.float64]:
    """Return a cleaned covariance estimate.

    Single-instrument / identity path is the only implemented method in Phase 8.
    Ledoit-Wolf / RMT raise ``RiskError`` directing callers to the multi-asset phase.
    """
    cfg = config or PortfolioConfig()
    cov = np.asarray(sample_cov, dtype=np.float64)
    if cov.ndim != 2 or cov.shape[0] != cov.shape[1]:
        raise RiskError("sample_cov must be square")
    if cfg.method == "identity":
        # No-op cleaning: return as-is (valid for 1x1)
        return cov
    raise RiskError(
        f"portfolio method {cfg.method!r} is deferred to the multi-asset phase "
        "(Ledoit-Wolf / RMT). Use method='identity' for single-instrument."
    )
