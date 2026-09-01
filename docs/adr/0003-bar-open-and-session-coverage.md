# ADR 0003 — Bar OPEN time and Dukascopy session coverage

**Status:** Accepted  
**Date:** 2026-08-31  
**Deciders:** fmengine Phase 2

## Context

Vendor timestamps and session calendars must not invent phantom bars or silently
accept look-ahead. Dukascopy 1m gold dumps include flat bars through the daily
rollover window, so excluding that window from "expected" minutes produced
coverage > 100%.

## Decision

- ``Bar.ts`` is the bar **OPEN** time, always tz-aware UTC.
- Session calendar for XAUUSD covers Sunday 22:00 UTC → Friday 21:00 UTC;
  holidays excluded; daily rollover remains in-session for coverage because the
  vendor emits bars there.
- Non-tradable periods are enforced via ``is_tradable`` (out-of-session OR flat
  runs of length ≥ 3), not by dropping rows from the catalog.
- QuestDB mirror uses CSV ``/imp`` with ``DROP TABLE`` + recreate for idempotent
  re-ingest (QuestDB 8.2 has no ``DELETE FROM``).

## Consequences

- Coverage is **in-session observed / calendar expected**; near 100% is healthy.
  Out-of-session vendor rows are retained but excluded from the coverage ratio.
- Strategies must filter ``is_tradable``.
- Large coverage deficits still signal missing data.
