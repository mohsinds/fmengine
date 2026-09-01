"""Feature pipeline + store tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import fmtrader.features  # noqa: F401
from fmtrader.core.errors import FeatureError
from fmtrader.features.pipeline import (
    feature_set_definition_hash,
    load_feature_set_yaml,
    validate_feature_set,
)
from fmtrader.features.store import definition_hash


class Caps:
    has_volume = False
    has_spread = False
    has_open_interest = False


def test_yaml_definition_produces_deterministic_hash(tmp_path: Path) -> None:
    payload = {
        "name": "t",
        "version": "1",
        "features": [{"indicator": "sma", "params": {"period": 20}, "alias": "a"}],
    }
    p = tmp_path / "f.yaml"
    p.write_text(yaml.safe_dump(payload), encoding="utf-8")
    d1 = load_feature_set_yaml(p)
    d2 = load_feature_set_yaml(p)
    assert feature_set_definition_hash(d1) == feature_set_definition_hash(d2)
    # Key order independence
    assert definition_hash({"b": 1, "a": 2}) == definition_hash({"a": 2, "b": 1})


def test_unavailable_feature_fails_before_any_computation() -> None:
    definition = {
        "name": "bad",
        "version": "1",
        "features": [{"indicator": "vwap", "params": {"period": 20}}],
    }
    with pytest.raises(FeatureError, match="has_volume"):
        validate_feature_set(definition, Caps(), dataset_id="gold_no_volume")


def test_hash_changes_when_yaml_changes() -> None:
    a = {"name": "t", "version": "1", "features": [{"indicator": "sma", "params": {"period": 20}}]}
    b = {"name": "t", "version": "1", "features": [{"indicator": "sma", "params": {"period": 21}}]}
    assert feature_set_definition_hash(a) != feature_set_definition_hash(b)
