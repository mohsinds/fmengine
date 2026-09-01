"""Adversarial leakage detectors for validation Phase 5."""

from __future__ import annotations

import ast
from typing import Any

import numpy as np

from fmtrader.core.errors import ValidationError
from fmtrader.features.leakage_audit import scan_source_for_leakage


def catch_shifted_label_leakage(labels: np.ndarray, features_at_t: np.ndarray) -> None:
    """Detect labels that are a pure shift of a future feature (planted bug)."""
    # If label[t] equals feature[t+1] for most t, it's shifted leakage
    if labels.size < 3 or features_at_t.size != labels.size:
        return
    match = np.isclose(labels[:-1], features_at_t[1:], equal_nan=False)
    if float(np.mean(match)) > 0.95:
        raise ValidationError("shifted label leakage detected")


def catch_centered_rolling_in_source(source: str) -> None:
    findings = scan_source_for_leakage(source)
    if any("center=True" in f for f in findings):
        raise ValidationError("centered rolling window leakage detected")


def catch_scaler_fit_on_full_series(
    *,
    scaler_max: float,
    train_max: float,
    full_max: float,
) -> None:
    """Detect scaler statistics fit including future rows beyond the train window."""
    if abs(scaler_max - full_max) <= 1e-12 and full_max > train_max + 1e-12:
        raise ValidationError("scaler fit on full series leakage detected")


def catch_same_bar_entry_exit(entry_i: int, exit_i: int) -> None:
    if entry_i == exit_i:
        raise ValidationError("same-bar entry and exit leakage detected")


def catch_future_regime_label(regime_at_t: np.ndarray, future_vol: np.ndarray) -> None:
    """Regime label correlated with future realized vol ⇒ look-ahead."""
    if regime_at_t.size < 10:
        return
    # Use next-bar vol as future
    fut = future_vol
    if fut.size != regime_at_t.size:
        return
    # Drop nan
    mask = np.isfinite(regime_at_t) & np.isfinite(fut)
    if mask.sum() < 10:
        return
    corr = float(np.corrcoef(regime_at_t[mask], fut[mask])[0, 1])
    if abs(corr) > 0.9:
        raise ValidationError("future regime label leakage detected")


def catch_target_encoded_with_future(
    encoded: np.ndarray,
    future_target: np.ndarray,
) -> None:
    """Target encoding that includes future rows will nearly equal future target mean patterns."""
    if encoded.size != future_target.size or encoded.size < 10:
        return
    mask = np.isfinite(encoded) & np.isfinite(future_target)
    if mask.sum() < 10:
        return
    corr = float(np.corrcoef(encoded[mask], future_target[mask])[0, 1])
    if abs(corr) > 0.95:
        raise ValidationError("target encoding with future data leakage detected")


def audit_strategy_source(source: str) -> list[str]:
    return scan_source_for_leakage(source)


def assert_no_ast_exec(source: str) -> None:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name in {"exec", "eval"}:
                raise ValidationError("exec/eval is forbidden in strategy proposals")


def detect_all_planted(checks: dict[str, Any]) -> list[str]:
    """Run a dict of planted checks; return list of catch messages."""
    caught: list[str] = []
    try:
        if "labels" in checks and "features" in checks:
            catch_shifted_label_leakage(checks["labels"], checks["features"])
    except ValidationError as exc:
        caught.append(str(exc))
    try:
        if "source" in checks:
            catch_centered_rolling_in_source(checks["source"])
    except ValidationError as exc:
        caught.append(str(exc))
    try:
        if "scaler_max" in checks:
            catch_scaler_fit_on_full_series(
                scaler_max=checks["scaler_max"],
                train_max=checks["train_max"],
                full_max=checks["full_max"],
            )
    except ValidationError as exc:
        caught.append(str(exc))
    try:
        if "entry_i" in checks:
            catch_same_bar_entry_exit(checks["entry_i"], checks["exit_i"])
    except ValidationError as exc:
        caught.append(str(exc))
    try:
        if "regime" in checks:
            catch_future_regime_label(checks["regime"], checks["future_vol"])
    except ValidationError as exc:
        caught.append(str(exc))
    try:
        if "encoded" in checks:
            catch_target_encoded_with_future(checks["encoded"], checks["future_target"])
    except ValidationError as exc:
        caught.append(str(exc))
    return caught
