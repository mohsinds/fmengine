# /new-strategy

Scaffold a new strategy end to end, wired into both backtest lanes.

**Usage:** `/new-strategy vwap_reversion` plus a description of the idea.

## Steps
1. **Restate the hypothesis** in one paragraph: what inefficiency is this exploiting, why should it
   persist, and in which regime would you expect it to fail? If you can't answer the third part,
   say so — that's a warning sign, not a formality.
2. **Check data requirements** against the active dataset manifest. If the strategy needs volume,
   spread, or order-book data the dataset lacks, stop and report it. Do not substitute a proxy silently.
3. Create `src/fmtrader/strategy/library/<name>.py` implementing the engine-agnostic `Strategy` base.
4. Declare a **parameter schema** (pydantic) and a **search space** (`strategy/space.py` DSL) with
   sensible ranges and any conditional dependencies between params.
5. Register it in `strategy/registry.py`.
6. Add a vectorbt lane adapter and a NautilusTrader lane adapter.
7. Tests: signal-generation correctness on a small hand-built fixture, warmup/NaN handling,
   no-signal-in-flat-bar-regions, and a parity check that both lanes agree on trade count and
   direction for a fixed seed and simple config.
8. Run a small sweep (≤ 200 configs) and report net-of-cost metrics, trial count, and cost drag.

## Do not
- Report a Sharpe without net-of-cost, trial count, and DSR context.
- Tune parameters against the holdout.
- Add a strategy that only works because of a data artifact — check the flat-bar regions first.
