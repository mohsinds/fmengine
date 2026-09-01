"""Purged / embargoed CV unit tests."""

from __future__ import annotations

import pytest

from fmtrader.backtest.validation.purged_cv import (
    assert_no_train_label_overlap,
    purged_kfold,
)
from fmtrader.core.errors import ValidationError


def test_no_train_sample_overlaps_test_label_window() -> None:
    folds = purged_kfold(600, n_folds=6, embargo=10, label_horizon=20)
    for f in folds:
        assert_no_train_label_overlap(f, label_horizon=20)


def test_embargo_excludes_correct_bar_count() -> None:
    folds = purged_kfold(600, n_folds=5, embargo=15, label_horizon=0)
    for f in folds:
        test_end = int(f.test_idx.max()) + 1
        embargo_zone = set(range(test_end, min(600, test_end + 15)))
        assert embargo_zone.isdisjoint(set(f.train_idx.tolist()))


def test_folds_are_contiguous_in_time() -> None:
    folds = purged_kfold(300, n_folds=6, embargo=0, label_horizon=0)
    for f in folds:
        idx = f.test_idx
        assert idx[-1] - idx[0] + 1 == idx.size


def test_purging_reduces_train_size_as_expected() -> None:
    no_purge = purged_kfold(500, n_folds=5, embargo=0, label_horizon=0)
    purged = purged_kfold(500, n_folds=5, embargo=0, label_horizon=25)
    assert sum(f.train_idx.size for f in purged) < sum(f.train_idx.size for f in no_purge)


def test_rejects_too_few_samples() -> None:
    with pytest.raises(ValidationError):
        purged_kfold(5, n_folds=6)
