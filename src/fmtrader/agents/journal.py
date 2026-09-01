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

    def read_report(self, campaign_id: str) -> str:
        index = self.campaign_dir(campaign_id) / "JOURNAL.md"
        if not index.exists():
            return f"No journal for campaign {campaign_id}"
        return index.read_text(encoding="utf-8")
