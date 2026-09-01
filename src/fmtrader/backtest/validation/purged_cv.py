"""Purged and embargoed K-fold cross-validation for overlapping labels."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fmtrader.core.errors import ValidationError


@dataclass(frozen=True)
class Fold:
    """Integer index ranges into a time-ordered sample array."""

    fold_id: int
    train_idx: np.ndarray
    test_idx: np.ndarray


def purged_kfold(
    n_samples: int,
    *,
    n_folds: int = 6,
    embargo: int = 0,
    label_horizon: int = 1,
) -> list[Fold]:
    """Purged K-fold with embargo after each test fold.

    Samples are assumed contiguous in time (index 0 … n-1).
    A training sample whose label window ``[i, i+label_horizon]`` overlaps the
    test fold is purged. An embargo of ``embargo`` bars after the test fold is
    also removed from training.
    """
    if n_samples < n_folds * 2:
        raise ValidationError(f"Need at least {n_folds * 2} samples for {n_folds} folds")
    if n_folds < 2:
        raise ValidationError("n_folds must be >= 2")
    if label_horizon < 0 or embargo < 0:
        raise ValidationError("label_horizon and embargo must be >= 0")

    fold_sizes = np.full(n_folds, n_samples // n_folds, dtype=int)
    fold_sizes[: n_samples % n_folds] += 1
    boundaries = np.cumsum(np.concatenate([[0], fold_sizes]))

    folds: list[Fold] = []
    all_idx = np.arange(n_samples)
    for k in range(n_folds):
        test_start = int(boundaries[k])
        test_end = int(boundaries[k + 1])  # exclusive
        test_idx = all_idx[test_start:test_end]
        if test_idx.size == 0:
            continue

        # Embargo immediately after test fold
        embargo_end = min(n_samples, test_end + embargo)

        train_mask = np.ones(n_samples, dtype=bool)
        train_mask[test_start:test_end] = False
        train_mask[test_end:embargo_end] = False

        # Purge: drop train i if [i, i+label_horizon] overlaps [test_start, test_end)
        if label_horizon > 0:
            # Overlap if i < test_end and i + label_horizon >= test_start
            # i.e. test_start - label_horizon <= i < test_end
            purge_lo = max(0, test_start - label_horizon)
            train_mask[purge_lo:test_end] = False
            # re-apply test+embargo already false

        train_idx = all_idx[train_mask]
        folds.append(Fold(fold_id=k, train_idx=train_idx, test_idx=test_idx))
    return folds


def assert_no_train_label_overlap(fold: Fold, *, label_horizon: int) -> None:
    """Raise if any train sample's label window overlaps the test fold."""
    if fold.test_idx.size == 0:
        return
    t0 = int(fold.test_idx.min())
    t1 = int(fold.test_idx.max()) + 1
    for i in fold.train_idx:
        # label window [i, i+label_horizon] inclusive end index i+label_horizon
        if i < t1 and (i + label_horizon) >= t0:
            raise ValidationError(f"Train sample {i} label window overlaps test [{t0}, {t1})")
