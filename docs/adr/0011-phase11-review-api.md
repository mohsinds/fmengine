# ADR 0011 — Phase 11 review API + web MVP

## Status
Accepted

## Context
FRONTEND_SPEC §7/§18 defines a large HTTP surface; B0–B11 is more than one session.
We need a frozen contract the Next.js client can call, with exit-criteria tests green.

## Decision
1. Ship FastAPI with the documented routes; wire real backends where they exist
   (executions, campaigns, registry, strategies, vault/kill-switch, system).
   Stub remaining analytics (robustness, MAE/MFE, lineage, agent-trace) as empty/safe payloads.
2. Equity display uses server-side LTTB downsampling (`?points=`).
3. SSE is throttled/batched at ≤4 Hz with `Last-Event-ID` resume.
4. Promotion is blocked when DSR gate fails (`POST .../promote` → 409); override requires justification + audit log.
5. `web/` is a dark Next.js shell with MetricsBlock (Sharpe+DSR+trials+cost drag indivisible)
   and OutcomeBlock (win rate + expectancy). SVG equity chart stands in for uPlot MVP.
6. IBKR/TWS and live Databento are out of scope for this UI phase.

## Consequences
- Full B10 Strategy Lab and uPlot/candle explorer remain follow-ups.
- `uv sync --extra api` (and `--extra tracking` for MLflow) required for API serve.
