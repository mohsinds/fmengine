"""Planted look-ahead bugs must be caught by the leakage auditor."""

from __future__ import annotations

import pytest

from fmtrader.core.errors import FeatureError
from fmtrader.features.leakage_audit import audit_paths, scan_source_for_leakage


def test_planted_centered_window_is_caught() -> None:
    src = """
import polars as pl
def bad(df):
    return df["close"].rolling_mean(window_size=5, center=True)
"""
    findings = scan_source_for_leakage(src, path="<planted>")
    assert any("center=True" in f for f in findings)


def test_planted_future_shift_is_caught() -> None:
    src = """
def bad(df):
    return df["close"].shift(-1)
"""
    findings = scan_source_for_leakage(src, path="<planted>")
    assert any("shift" in f for f in findings)


def test_real_indicator_sources_pass_audit() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "src" / "fmtrader" / "features"
    paths = list(root.rglob("*.py"))
    # Should not raise on the real library
    audit_paths(paths)


def test_audit_paths_raises_on_temp_file(tmp_path: object) -> None:
    from pathlib import Path

    p = Path(str(tmp_path)) / "bad.py"
    p.write_text("x.rolling_mean(5, center=True)\n", encoding="utf-8")
    with pytest.raises(FeatureError, match="Leakage audit"):
        audit_paths([p])
