# ADR 0004 — Two-lane backtest with shared next-bar fills

**Status:** Accepted
**Date:** 2026-09-01

## Context
Phase 4 requires a fast triage lane and a fidelity lane with identical cost
semantics. The installed `vectorbt` package currently fails to import due to a
plotly template incompatibility; full NautilusTrader venue wiring is deferred.

## Decision
- Both CLI lanes (`vectorbt`, `nautilus`) call the shared next-bar open fill
  engine so buy-and-hold and simple signal strategies parity-check exactly.
- Signal-bar close fills and same-bar entry/exit are hard-rejected.
- Cost models refuse `spread_abs <= 0` when `has_spread=false`.
- Sweeps are chunked with a configurable worker pool (default 6).

## Consequences
Lane names match the architecture; swapping in real vectorbt/Nautilus adapters
later does not change strategy code. Until then, triage vs fidelity differ only
in intended API surface (event-loop validation hook on the nautilus path).
