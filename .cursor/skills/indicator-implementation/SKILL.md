---
name: indicator-implementation
description: Use when implementing, reviewing, or debugging any technical indicator or feature in fmtrader — trend, momentum, volatility, volume, microstructure, regime, or labeling functions. Covers the required signature, capability declaration, warmup semantics, and test obligations.
---

# Implementing an indicator in fmtrader

## Required shape

Every indicator is a pure, vectorized function plus a registry declaration.

```python
@register_indicator(
    name="atr",
    category="volatility",
    requires=("high", "low", "close"),
    requires_volume=False,
    min_lookback=lambda p: p["period"] + 1,
    params_schema=ATRParams,
)
def atr(df: pl.DataFrame, period: int = 14) -> pl.Series:
    """Average True Range (Wilder smoothing).

    Returns a Series aligned to df["ts"], with the first `period` values null.
    Uses only data at or before each bar. Never centers.
    """
```

## Rules

1. **Pure.** No IO, no global state, no mutation of the input frame. Same input → same output, always.
2. **Trailing only.** Every window is strictly backward-looking. `center=True` is a bug.
3. **Explicit warmup.** The first `min_lookback` values are `null`, never forward-filled, never zero.
   Downstream code decides how to handle them; the indicator does not decide for it.
4. **Declare capabilities.** `requires_volume=True` on a volume indicator is what lets the pipeline
   fail loudly on the current volume-less gold dataset instead of returning silent NaNs.
5. **Polars-native.** Use Polars expressions. Drop to NumPy only for genuinely recursive computations
   (Wilder smoothing, some adaptive filters) and document why.
6. **Parameterized, not hardcoded.** Every constant that affects output is a schema field.
7. **Numerically safe.** Guard divide-by-zero, constant series, and near-zero denominators explicitly.

## Test obligations — all four, no exceptions

- **Correctness:** compare against a hand-computed value or a trusted reference implementation on a
  small fixture. Record the reference in the test so it's auditable.
- **Warmup:** assert exactly `min_lookback` leading nulls, and that value `n` never depends on `n+1`.
  A good direct test: compute on the full series, compute on the series truncated at `n`, assert the
  value at `n` matches. This catches look-ahead better than reading the code.
- **Degenerate input:** constant series, single row, all-null column, insufficient lookback.
- **Property test:** state an invariant with `hypothesis`. Examples:
  `bb_lower ≤ sma ≤ bb_upper` · `0 ≤ rsi ≤ 100` · `atr ≥ 0` · `donchian_low ≤ close ≤ donchian_high`.

## Volatility estimators worth having
Beyond ATR: Parkinson (high-low), Garman-Klass (OHLC), Rogers-Satchell (drift-robust), Yang-Zhang
(handles overnight gaps). They differ in efficiency and assumptions — document which assumption each
makes, since gold's 23-hour session with a daily break violates some of them.

## Regime features
Quantile volatility regime: rank current realized vol within its trailing distribution and bucket into
discrete regimes. Keep the ranking window trailing and the bucket edges fixed in config, not fit to the
full sample — fitting bucket edges on all data is leakage.

## Naming
`<category>_<name>_<key_params>` in the feature store, e.g. `volatility_atr_14`, `momentum_rsi_2`.
Deterministic naming makes feature sets diffable and cacheable.
