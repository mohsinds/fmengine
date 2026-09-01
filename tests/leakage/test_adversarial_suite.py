"""Adversarial leakage suite — every planted bug must be caught."""

from __future__ import annotations

import numpy as np
import pytest

from fmtrader.backtest.validation.leakage import (
    catch_centered_rolling_in_source,
    catch_future_regime_label,
    catch_same_bar_entry_exit,
    catch_scaler_fit_on_full_series,
    catch_shifted_label_leakage,
    catch_target_encoded_with_future,
)
from fmtrader.core.errors import ValidationError


def test_catches_shifted_label_leakage() -> None:
    feat = np.arange(100, dtype=float)
    labels = np.concatenate([[np.nan], feat[1:]])  # label[t] ≈ feature[t] shifted wrong way
    # Plant: labels[t] = feature[t+1]
    labels = np.zeros(100)
    labels[:-1] = feat[1:]
    with pytest.raises(ValidationError, match="shifted label"):
        catch_shifted_label_leakage(labels, feat)


def test_catches_centered_rolling_window() -> None:
    src = "df['close'].rolling_mean(window_size=20, center=True)"
    with pytest.raises(ValidationError, match="centered rolling"):
        catch_centered_rolling_in_source(src)


def test_catches_scaler_fit_on_full_series() -> None:
    with pytest.raises(ValidationError, match="scaler fit on full series"):
        catch_scaler_fit_on_full_series(scaler_max=10.0, train_max=8.0, full_max=10.0)


def test_catches_same_bar_entry_exit() -> None:
    with pytest.raises(ValidationError, match="same-bar"):
        catch_same_bar_entry_exit(5, 5)


def test_catches_future_regime_label() -> None:
    rng = np.random.default_rng(0)
    future_vol = rng.normal(size=200)
    regime = future_vol.copy()  # planted: regime is future vol itself
    with pytest.raises(ValidationError, match="future regime"):
        catch_future_regime_label(regime, future_vol)


def test_catches_target_encoded_with_future() -> None:
    rng = np.random.default_rng(1)
    future = rng.normal(size=200)
    encoded = future.copy()
    with pytest.raises(ValidationError, match="target encoding"):
        catch_target_encoded_with_future(encoded, future)
