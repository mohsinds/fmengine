"""Research journal — human-readable Markdown per generation."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def render_generation_markdown(
    *,
    campaign_id: str,
    generation: int,
    hypothesis: str,
    proposals: list[dict[str, Any]],
    results: list[dict[str, Any]],
    survivors: list[dict[str, Any]],
    next_search_space: dict[str, Any] | None,
    critique: str,
    decision: str,
) -> str:
    lines = [
        f"# Campaign `{campaign_id}` — Generation {generation}",
        "",
        f"_Written {datetime.now(tz=UTC).isoformat()}_",
        "",
        "## Hypothesis",
        "",
        hypothesis or "(none)",
        "",
        "## Proposals evaluated",
        "",
    ]
    if not proposals:
        lines.append("_No proposals._")
    else:
        for i, p in enumerate(proposals):
            lines.append(
                f"{i + 1}. strategy=`{p.get('strategy')}` params=`{p.get('params')}` "
                f"— {p.get('rationale', '')}"
            )
    lines.extend(["", "## Results (net)", ""])
    if not results:
        lines.append("_No results._")
    else:
        lines.append("| strategy | sharpe | return | trades | verdict |")
        lines.append("|---|---:|---:|---:|---|")
        for r in results:
            lines.append(
                f"| {r.get('strategy')} | {r.get('sharpe', '')} | "
                f"{r.get('total_return_net', r.get('return', ''))} | "
                f"{r.get('trade_count', '')} | {r.get('verdict', '')} |"
            )
    lines.extend(["", "## Survivors", ""])
    if not survivors:
        lines.append("_None — generation produced no survivors._")
    else:
        for s in survivors:
            lines.append(f"- `{s.get('strategy')}` {s.get('params')} sharpe={s.get('sharpe')}")
    lines.extend(
        [
            "",
            "## Critique",
            "",
            critique or "(none)",
            "",
            "## Decision",
            "",
            decision or "(none)",
            "",
            "## Next search space",
            "",
            f"```json\n{next_search_space or {}}\n```",
            "",
        ]
    )
    return "\n".join(lines)


class ResearchJournal:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path("data/journals")
        self.root.mkdir(parents=True, exist_ok=True)

    def campaign_dir(self, campaign_id: str) -> Path:
        d = self.root / campaign_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def write_generation(
        self,
        *,
        campaign_id: str,
        generation: int,
        hypothesis: str,
        proposals: list[dict[str, Any]],
        results: list[dict[str, Any]],
        survivors: list[dict[str, Any]],
        next_search_space: dict[str, Any] | None,
        critique: str,
        decision: str,
    ) -> Path:
        md = render_generation_markdown(
            campaign_id=campaign_id,
            generation=generation,
            hypothesis=hypothesis,
            proposals=proposals,
            results=results,
            survivors=survivors,
            next_search_space=next_search_space,
            critique=critique,
            decision=decision,
        )
        path = self.campaign_dir(campaign_id) / f"generation_{generation:04d}.md"
        path.write_text(md, encoding="utf-8")
        # Append to rolling journal
        index = self.campaign_dir(campaign_id) / "JOURNAL.md"
        with index.open("a", encoding="utf-8") as fh:
            fh.write(md)
            fh.write("\n\n---\n\n")
        return path

    def write_summary(self, campaign_id: str, summary: dict[str, Any]) -> Path:
        lines = [
            f"# Campaign `{campaign_id}` — Leaderboard Summary",
            "",
            f"_Written {datetime.now(tz=UTC).isoformat()}_",
            "",
            f"Trials recorded: **{summary.get('n_trials')}** · scored: **{summary.get('n_scored')}**",
            "",
            "## Best overall",
            "",
        ]
        best = summary.get("best_overall")
        if not best:
            lines.append("_No scored trials._")
        else:
            lines.extend(
                [
                    f"- **strategy:** `{best.get('strategy')}`",
                    f"- **params:** `{best.get('params')}`",
                    f"- **Sharpe (net):** {best.get('sharpe')}",
                    f"- **DSR:** {best.get('dsr')}",
                    f"- **PBO:** {best.get('pbo')} _(placeholder until CSCV)_",
                    f"- **cost drag %:** {best.get('cost_drag_pct')}",
                    f"- **trades:** {best.get('trade_count')}",
                    f"- **verdict:** {best.get('verdict')}",
                    f"- **generation:** {best.get('generation')}",
                    "",
                    "## Why",
                    "",
                    str(summary.get("why") or ""),
                ]
            )
        lines.extend(["", "## Best by strategy", ""])
        by_s = summary.get("best_by_strategy") or {}
        if not by_s:
            lines.append("_None._")
        else:
            lines.append("| strategy | sharpe | dsr | cost_drag% | trades | verdict | params |")
            lines.append("|---|---:|---:|---:|---:|---|---|")
            for name, r in sorted(by_s.items()):
                lines.append(
                    f"| {name} | {r.get('sharpe')} | {r.get('dsr')} | "
                    f"{r.get('cost_drag_pct')} | {r.get('trade_count')} | "
                    f"{r.get('verdict')} | `{r.get('params')}` |"
                )
        lines.extend(["", "## Top 10", ""])
        top = summary.get("top10") or []
        if not top:
            lines.append("_None._")
        else:
            lines.append("| # | strategy | sharpe | dsr | cost_drag% | trades | verdict |")
            lines.append("|---:|---|---:|---:|---:|---:|---|")
            for i, r in enumerate(top, 1):
                lines.append(
                    f"| {i} | {r.get('strategy')} | {r.get('sharpe')} | {r.get('dsr')} | "
                    f"{r.get('cost_drag_pct')} | {r.get('trade_count')} | {r.get('verdict')} |"
                )
        md = "\n".join(lines) + "\n"
        path = self.campaign_dir(campaign_id) / "SUMMARY.md"
        path.write_text(md, encoding="utf-8")
        index = self.campaign_dir(campaign_id) / "JOURNAL.md"
        with index.open("a", encoding="utf-8") as fh:
            fh.write(md)
            fh.write("\n\n---\n\n")
        return path

    def read_report(self, campaign_id: str) -> str:
        index = self.campaign_dir(campaign_id) / "JOURNAL.md"
        summary = self.campaign_dir(campaign_id) / "SUMMARY.md"
        parts: list[str] = []
        if summary.exists():
            parts.append(summary.read_text(encoding="utf-8"))
        if index.exists():
            parts.append(index.read_text(encoding="utf-8"))
        if not parts:
            return f"No journal for campaign {campaign_id}"
        return "\n\n".join(parts)
