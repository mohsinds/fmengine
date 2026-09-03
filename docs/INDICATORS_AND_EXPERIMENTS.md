# Indicators and experiments

## Who chooses indicators today?

**Not the LLM.** Lab and agentic campaigns select among **registered strategies** and
tune **parameters inside YAML search spaces**. The indicator family is fixed inside
each strategy’s Python module.

| Goal | Edit |
|------|------|
| Tune params in Lab | Strategy form fields from `params_schema` |
| Expand agent search grids | `configs/spaces/*.yaml` |
| Change which indicator a strategy uses | New/edited module under `src/fmtrader/strategy/library/` |
| Change research feature matrix (ML path) | `configs/features/*.yaml` + `fmtrader features build` |
| Volume / Hawkes / VWAP | Requires dataset `has_volume=true` (blocked on XAUUSD bid-only) |

Every Lab run still writes to the **trial registry** (`source=manual`) — manual tuning
is multiple testing.

## Three lanes

1. **Lab / backtests / campaigns** — strategy code computes indicators on bars (e.g.
   `ema_cross` → EMA). Feature-store YAML is **not** consulted.
2. **Feature store** — `configs/features/baseline.yaml` builds dense columns via the
   indicator registry for offline research matrices.
3. **Providers** — technical / news / sentiment adapters compose into feature builds;
   not on the live order path.

## Registered indicator families (OHLC-safe unless noted)

- Trend: sma, ema, wma, hma, dema, tema, adx, aroon, supertrend, …
- Momentum: rsi, macd, stochastic, cci, …
- Volatility: atr, bollinger, keltner, realized_vol, …
- Regime: `quantile_vol_regime`
- Volume-gated: vwap, obv, mfi, `hawkes_intensity` → **error** if `has_volume=false`

## Agentic ingredient proposals

Campaigns with `allow_ingredient_proposals: true` may propose tools from a **curated
catalog** (fractional Kelly, conformal filter, vol regime, …). Unknown names are
rejected. Volume/multi-asset tools are skipped on the current gold bid dataset.

Validated recipes are **applied** via `apply_ingredient_recipe` (sizing / stop /
regime annotations on campaign state + scored rows). `conformal_filter` stays
`deferred` until a fitted artifact exists — no fake signals. Hawkes / RMT stay
rejected on bid-only data.

See `src/fmtrader/agents/ingredients.py`, `apply_ingredients.py`, and
`GET /api/ingredients`.

## Agent memory ≠ fine-tuning

`use_agent_memory: true` injects a retrieval summary from the trial registry and
recent journals into hypothesize / critique / ingredient prompts. Lab chats do not
update model weights. Ingredients are not free-form indicators — catalog only.

## Lab tip

When you pick a strategy in the Lab, you are picking that strategy’s indicator
family. To experiment with RSI instead of EMA, choose `rsi_mean_reversion` (or add a
new strategy module) — do not expect the agent to invent a new indicator mid-run.
