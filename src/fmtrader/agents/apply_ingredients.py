"""Apply validated ingredient recipes onto campaign generation results."""

from __future__ import annotations

from typing import Any

from fmtrader.agents.campaign import CampaignState
from fmtrader.system.logging import get_logger

log = get_logger(__name__)


def apply_ingredient_recipe(
    state: CampaignState,
    recipe: dict[str, Any],
    *,
    results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Annotate state/results with sizing / regime / conformal flags.

    Does not invent signals. Deferred ingredients are recorded with reasons.
    """
    accepted = [str(x) for x in (recipe.get("ingredients") or [])]
    params = dict(recipe.get("params") or {})
    applied: list[str] = []
    deferred: list[dict[str, str]] = []
    annotations: dict[str, Any] = {
        "sizing": {},
        "regime": {},
        "conformal": {},
        "stops": {},
    }

    for name in accepted:
        if name == "fractional_kelly":
            frac = float(params.get("kelly_fraction", 0.25))
            annotations["sizing"] = {
                "method": "fractional_kelly",
                "kelly_fraction": frac,
                "max_risk_per_trade": float(params.get("max_risk_per_trade", 0.01)),
            }
            applied.append(name)
        elif name == "fixed_pct_risk":
            annotations["sizing"] = {
                "method": "fixed_pct_risk",
                "risk_pct": float(params.get("risk_pct", 0.01)),
            }
            applied.append(name)
        elif name == "vol_stop":
            annotations["stops"] = {
                "method": "vol_stop",
                "atr_mult": float(params.get("atr_mult", 2.0)),
            }
            applied.append(name)
        elif name == "vol_regime_quantile":
            annotations["regime"] = {
                "method": "vol_regime_quantile",
                "note": "segment metrics by quantile vol regime when feature available",
            }
            applied.append(name)
        elif name == "conformal_filter":
            # Only enable if caller later supplies a fitted gate; mark deferred otherwise
            deferred.append(
                {
                    "name": name,
                    "reason": "requires_fitted_conformal_artifact",
                }
            )
        else:
            deferred.append({"name": name, "reason": "no_apply_handler"})

    rejected = list(recipe.get("rejected") or []) + deferred
    out_recipe = {
        "ingredients": applied,
        "params": params,
        "rejected": rejected,
        "annotations": annotations,
    }
    state.active_ingredients = list(applied)
    state.ingredient_annotations = annotations

    if results is not None:
        for row in results:
            row["ingredients"] = list(applied)
            row["ingredient_annotations"] = annotations

    log.info(
        "ingredients_applied",
        campaign_id=state.campaign_id,
        applied=applied,
        deferred=[d["name"] for d in deferred],
    )
    return out_recipe


def merge_proposal_ingredients(
    generation_recipe: dict[str, Any],
    proposals: list[dict[str, Any]],
    *,
    has_volume: bool = False,
) -> dict[str, Any]:
    """Merge optional per-proposal ingredient lists into the generation recipe."""
    from fmtrader.agents.ingredients import validate_ingredient_recipe

    names = list(generation_recipe.get("ingredients") or [])
    for p in proposals:
        extra = p.get("ingredients")
        if isinstance(extra, list):
            names.extend(str(x) for x in extra)
    validated = validate_ingredient_recipe(
        {"ingredients": names, "params": generation_recipe.get("params") or {}},
        has_volume=has_volume,
    )
    return validated.recipe
