"""SSE helpers — batch + throttle campaign/run/system streams."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass
from typing import Any

DEFAULT_MAX_HZ = 4.0  # client must never see more than ~4 updates/sec


@dataclass
class SseEvent:
    event: str
    data: dict[str, Any]
    id: str | None = None

    def encode(self) -> str:
        lines: list[str] = []
        if self.id is not None:
            lines.append(f"id: {self.id}")
        lines.append(f"event: {self.event}")
        payload = json.dumps(self.data, default=str)
        lines.append(f"data: {payload}")
        lines.append("")
        return "\n".join(lines) + "\n"


async def throttled_sse(
    produce: Callable[[], Iterable[SseEvent] | list[SseEvent]],
    *,
    max_hz: float = DEFAULT_MAX_HZ,
    last_event_id: str | None = None,
    idle_sleep: float = 0.25,
    max_iterations: int | None = None,
) -> AsyncIterator[str]:
    """Yield SSE frames, batching producer output and throttling to ``max_hz``.

    ``last_event_id`` enables resume: events with id <= last are skipped when comparable.
    """
    min_interval = 1.0 / max_hz if max_hz > 0 else 0.0
    last_emit = 0.0
    pending: list[SseEvent] = []
    iterations = 0
    seen_resume = last_event_id is None

    while True:
        if max_iterations is not None and iterations >= max_iterations:
            break
        iterations += 1
        batch = list(produce())
        for ev in batch:
            if last_event_id is not None and not seen_resume:
                if ev.id is not None and ev.id <= last_event_id:
                    continue
                seen_resume = True
            pending.append(ev)

        now = time.monotonic()
        if pending and (now - last_emit) >= min_interval:
            # Batch: emit a single envelope when multiple pending
            if len(pending) == 1:
                yield pending[0].encode()
            else:
                envelope = SseEvent(
                    event="batch",
                    data={
                        "events": [{"event": e.event, "data": e.data, "id": e.id} for e in pending]
                    },
                    id=pending[-1].id,
                )
                yield envelope.encode()
            pending.clear()
            last_emit = now

        await asyncio.sleep(idle_sleep)
