"""Retrieval-augmented agent memory from trial registry + journals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fmtrader.backtest.validation.registry import TrialRecord, default_registry
from fmtrader.system.logging import get_logger

log = get_logger(__name__)


def _sharpe(trial: TrialRecord) -> float:
    m = trial.metrics or {}
    for key in ("sharpe", "sharpe_net", "net_sharpe"):
        v = m.get(key)
        if isinstance(v, (int, float)):
            return float(v)
    return float("-inf")


def _cost_drag(trial: TrialRecord) -> float | None:
    m = trial.metrics or {}
    v = m.get("cost_drag_pct")
    return float(v) if isinstance(v, (int, float)) else None


def summarize_trials(
    trials: list[TrialRecord],
    *,
    strategies: list[str] | None = None,
    limit: int = 20,
) -> str:
    """Rank trials and render a compact memory block for LLM prompts."""
    strat_set = set(strategies or [])
    filtered = [
        t
        for t in trials
        if (not strat_set or t.strategy in strat_set) and _sharpe(t) > float("-inf")
    ]
    filtered.sort(key=_sharpe, reverse=True)
    if not filtered:
        return "(no prior scored trials in registry for these strategies)"

    top = filtered[: max(1, limit // 2)]
    bottom = list(reversed(filtered[-max(1, limit // 4) :])) if len(filtered) > 3 else []
    lines = [
        f"Prior trials in registry: {len(filtered)} scored "
        f"(showing top {len(top)}"
        + (f", weak {len(bottom)}" if bottom else "")
        + ").",
        "Prefer exploring near strong configs; avoid exact duplicates (registry dedupes).",
        "",
        "## Strong prior configs",
    ]
    for t in top:
        drag = _cost_drag(t)
        drag_s = f", cost_drag={drag:.2f}%" if drag is not None else ""
        verdict = (t.metrics or {}).get("verdict", "")
        lines.append(
            f"- [{t.source}] {t.strategy} params={json.dumps(t.params, sort_keys=True)} "
            f"sharpe={_sharpe(t):.4f}{drag_s} verdict={verdict}"
        )
    if bottom:
        lines.append("")
        lines.append("## Weak / cautionary configs")
        for t in bottom:
            lines.append(
                f"- [{t.source}] {t.strategy} params={json.dumps(t.params, sort_keys=True)} "
                f"sharpe={_sharpe(t):.4f}"
            )
    return "\n".join(lines)


def _ingredient_hints_from_traces(journal_root: Path, *, limit: int = 30) -> str:
    """Scan recent trace.jsonl files for ingredient recipes that co-occurred with decisions."""
    if not journal_root.exists():
        return ""
    rows: list[dict[str, Any]] = []
    for trace in sorted(journal_root.glob("*/trace.jsonl"), reverse=True)[:20]:
        try:
            for line in trace.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except OSError:
            continue
        if len(rows) >= limit * 2:
            break
    if not rows:
        return ""
    # Count ingredient frequency
    counts: dict[str, int] = {}
    for ev in rows[-limit:]:
        ing = (ev.get("ingredients") or {}).get("ingredients") or []
        if isinstance(ing, list):
            for name in ing:
                counts[str(name)] = counts.get(str(name), 0) + 1
    if not counts:
        return ""
    ranked = sorted(counts.items(), key=lambda x: -x[1])
    parts = [f"{n}×{c}" for n, c in ranked[:8]]
    return "Recently applied ingredients (freq): " + ", ".join(parts)


def build_agent_memory(
    *,
    dataset_id: str,
    strategies: list[str],
    limit: int = 20,
    registry_path: Path | None = None,
    journal_root: Path | None = None,
    decision_trace: list[dict[str, Any]] | None = None,
) -> str:
    """Build retrieval block for hypothesize / critique / ingredient prompts."""
    sections: list[str] = [f"Dataset focus: {dataset_id}", f"Strategies in scope: {strategies}"]
    try:
        reg = (
            default_registry(registry_path.parent)
            if registry_path is not None
            else default_registry()
        )
        # Prefer dataset-matched trials
        all_trials = reg.list_trials()
        matched = [t for t in all_trials if t.dataset_id == dataset_id]
        pool = matched if matched else all_trials
        sections.append(summarize_trials(pool, strategies=strategies, limit=limit))
    except Exception as exc:  # noqa: BLE001
        log.warning("agent_memory_registry_failed", error=str(exc))
        sections.append("(trial registry unavailable)")

    jroot = journal_root or Path("data/journals")
    hint = _ingredient_hints_from_traces(jroot, limit=limit)
    if hint:
        sections.append(hint)

    if decision_trace:
        recent = decision_trace[-3:]
        sections.append("## Recent campaign decisions")
        for ev in recent:
            gen = ev.get("generation")
            ings = (ev.get("ingredients") or {}).get("ingredients") or []
            dec = str(ev.get("decision") or "")[:200]
            sections.append(f"- gen={gen} ingredients={ings} decision={dec}")

    return "\n".join(sections)
