"""Signal funnel — counts and drop reasons between stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

STAGES = (
    "raw_signals",
    "after_regime",
    "after_gate",
    "after_risk",
    "orders",
    "fills",
)


@dataclass
class Funnel:
    """Monotonic non-increasing stage counts with drop reasons."""

    counts: dict[str, int] = field(default_factory=lambda: {s: 0 for s in STAGES})
    drops: dict[str, dict[str, int]] = field(default_factory=dict)

    def set_count(self, stage: str, n: int) -> None:
        if stage not in self.counts:
            raise KeyError(stage)
        self.counts[stage] = int(n)

    def add_drop(self, stage: str, reason: str, n: int = 1) -> None:
        bucket = self.drops.setdefault(stage, {})
        bucket[reason] = bucket.get(reason, 0) + int(n)

    def validate(self) -> None:
        prev = None
        for stage in STAGES:
            n = self.counts[stage]
            if prev is not None and n > prev:
                raise ValueError(f"Funnel not monotonic at {stage}: {n} > {prev}")
            prev = n
        for a, b in pairwise(STAGES):
            diff = self.counts[a] - self.counts[b]
            dropped = sum(self.drops.get(b, {}).values())
            if dropped and dropped != diff:
                alt = sum(self.drops.get(f"{a}->{b}", {}).values())
                if alt != diff and dropped != diff:
                    raise ValueError(f"Drop reasons for {a}->{b} sum to {dropped}, expected {diff}")

    def to_dict(self) -> dict[str, Any]:
        return {"counts": dict(self.counts), "drops": {k: dict(v) for k, v in self.drops.items()}}
