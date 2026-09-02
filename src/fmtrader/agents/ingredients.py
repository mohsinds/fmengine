"""Curated experiment ingredient catalog — agents may only propose from this list."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from fmtrader.core.errors import AgentError

Capability = Literal["none", "volume", "spread", "model_artifact", "multi_asset"]


@dataclass(frozen=True)
class IngredientSpec:
    name: str
    description: str
    requires: Capability = "none"
    implemented: bool = True
    """False = catalog stub (may be proposed but skipped with reason)."""


INGREDIENT_CATALOG: dict[str, IngredientSpec] = {
    "vol_regime_quantile": IngredientSpec(
        name="vol_regime_quantile",
        description="Quantile volatility regime label (OHLC-safe).",
    ),
    "conformal_filter": IngredientSpec(
        name="conformal_filter",
        description="Reject/shrink signals with wide conformal uncertainty.",
    ),
    "fractional_kelly": IngredientSpec(
        name="fractional_kelly",
        description="Position size via fractional Kelly (default fraction 0.25).",
    ),
    "fixed_pct_risk": IngredientSpec(
        name="fixed_pct_risk",
        description="Fixed percentage risk per trade.",
    ),
    "vol_stop": IngredientSpec(
        name="vol_stop",
        description="Volatility-based stop distance (ATR/regime aware).",
    ),
    "bayesian_direction": IngredientSpec(
        name="bayesian_direction",
        description="Bayesian direction probability when a calibrated model artifact exists.",
        requires="model_artifact",
        implemented=False,
    ),
    "hawkes_clustering": IngredientSpec(
        name="hawkes_clustering",
        description="Hawkes intensity / clustering — requires trade/volume arrivals.",
        requires="volume",
    ),
    "rmt_corr": IngredientSpec(
        name="rmt_corr",
        description="Random matrix correlation cleaning — multi-asset only.",
        requires="multi_asset",
        implemented=False,
    ),
}


@dataclass
class IngredientValidation:
    accepted: list[str]
    rejected: list[dict[str, str]]
    recipe: dict[str, Any]


def list_ingredients(*, available_only: bool = False) -> list[dict[str, Any]]:
    rows = []
    for spec in INGREDIENT_CATALOG.values():
        if available_only and not spec.implemented:
            continue
        rows.append(
            {
                "name": spec.name,
                "description": spec.description,
                "requires": spec.requires,
                "implemented": spec.implemented,
            }
        )
    return rows


def validate_ingredient_recipe(
    raw: object,
    *,
    has_volume: bool = False,
    has_spread: bool = False,
    has_model_artifact: bool = False,
    multi_asset: bool = False,
) -> IngredientValidation:
    """Accept only catalog names that pass dataset capability gates."""
    if raw is None:
        return IngredientValidation(accepted=[], rejected=[], recipe={"ingredients": []})

    names: list[str] = []
    params: dict[str, Any] = {}
    if isinstance(raw, dict):
        ing = raw.get("ingredients") or raw.get("recipe") or raw.get("names") or []
        if isinstance(ing, list):
            names = [str(x) for x in ing]
        elif isinstance(ing, str):
            names = [ing]
        if isinstance(raw.get("params"), dict):
            params = dict(raw["params"])
    elif isinstance(raw, list):
        names = [str(x) for x in raw]
    else:
        raise AgentError(f"Ingredient recipe must be dict or list, got {type(raw)}")

    caps = {
        "none": True,
        "volume": has_volume,
        "spread": has_spread,
        "model_artifact": has_model_artifact,
        "multi_asset": multi_asset,
    }
    accepted: list[str] = []
    rejected: list[dict[str, str]] = []
    seen: set[str] = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        spec = INGREDIENT_CATALOG.get(name)
        if spec is None:
            rejected.append({"name": name, "reason": "unknown_ingredient"})
            continue
        if not caps.get(spec.requires, False):
            rejected.append(
                {
                    "name": name,
                    "reason": f"requires_{spec.requires}_unavailable",
                }
            )
            continue
        if not spec.implemented:
            rejected.append({"name": name, "reason": "not_implemented_stub"})
            continue
        accepted.append(name)

    recipe = {"ingredients": accepted, "params": params, "rejected": rejected}
    return IngredientValidation(accepted=accepted, rejected=rejected, recipe=recipe)


def parse_ingredients_from_llm_text(text: str) -> object | None:
    """Extract JSON object/array mentioning ingredients from LLM text."""
    import json
    import re

    text = (text or "").strip()
    if not text:
        return None
    # Prefer fenced JSON
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    blob = fence.group(1).strip() if fence else text
    # Find first { or [
    start_obj = blob.find("{")
    start_arr = blob.find("[")
    starts = [i for i in (start_obj, start_arr) if i >= 0]
    if not starts:
        return None
    start = min(starts)
    try:
        return json.loads(blob[start:])
    except json.JSONDecodeError:
        # Truncate to last brace
        for end in range(len(blob), start, -1):
            try:
                return json.loads(blob[start:end])
            except json.JSONDecodeError:
                continue
    return None
