---
name: data-onboarding
description: Use when ingesting a new dataset, writing a vendor adapter, debugging data quality, building continuous futures contracts, or deciding whether a dataset can support a given feature or strategy in fmtrader.
---

# Onboarding data into fmtrader

## Step 1 — capability audit before writing any code

Answer these, in writing, before the adapter exists:

| Question | Why it matters |
|---|---|
| Real traded volume, or a tick-count proxy? | Determines whether VWAP/OBV/volume-profile are meaningful or fiction |
| Bid, ask, mid, or last? | Bid-only means spread is unmeasurable and costs must be assumed |
| Open interest available? | Futures conviction signals, roll rules |
| Order book depth? | Microstructure features, Hawkes intensity |
| Session calendar and holidays? | Correct gap classification |
| Timestamp: exchange time or vendor time? Bar-open or bar-close? Timezone? | Silent misalignment is a top source of fake edges |
| Revision policy — is history ever restated? | Restated data is look-ahead bias |
| Corporate actions (equities) / funding (perps) / rolls (futures)? | Return calculation correctness |

Record the answers in the adapter's capability declaration. Downstream gating depends on them.

## Step 2 — the current gold dataset, concretely

`download/xauusd-m1-bid-2021-01-01-2026-08-31.csv`, columns `timestamp,open,high,low,close`.

- `timestamp` = **epoch milliseconds, UTC**.
- **No volume, bid side only.** Manifest: `has_volume: false`, `has_spread: false`, `side: "bid"`.
- Unavailable on this dataset, and must raise rather than return NaN: VWAP and anchored VWAP, OBV,
  MFI, volume profile / POC, cumulative delta, order-book imbalance, Hawkes trade-arrival intensity,
  any spread-derived feature.
- **Flat bars** (`open == high == low == close`, often repeating) mark no-tick periods — weekends,
  holidays, thin hours. Detect runs of them, flag the bars as non-tradable, and exclude them from
  signal generation. A strategy that appears to profit inside these regions is an artifact.
- To recover spread: download the ask side separately and derive it. Until then, cost models use a
  conservative constant from config — never zero.

## Step 3 — quality gate

Hard-fail on: non-monotonic or duplicate timestamps · OHLC invariant violations
(`low ≤ min(open, close)`, `high ≥ max(open, close)`, all strictly positive) · impossible values.

Report (don't fail) on: gaps classified against the session calendar (weekend / holiday / rollover /
anomalous) · MAD-based return outliers · flat-bar run lengths and counts · monthly coverage percentage.

Print coverage as a month-by-month table. Eyeballing that table catches vendor problems that no
automated check anticipates.

## Step 4 — snapshot manifest

Write `data/snapshots/<dataset_id>.json` with a content hash over the canonical Parquet. Every
downstream artifact references `dataset_id` + `content_hash`. Results without one are rejected at
write time — this is what makes a six-month-old backtest reproducible.

## Step 5 — continuous futures contracts (CME phase)

You cannot trade a continuous contract; it is a research construct. Keep raw per-contract data
alongside it, always.

- **Back-adjusted (Panama):** subtract the roll gap cumulatively. Preserves price *differences*, so
  ATR and other difference-based indicators stay correct. Distorts absolute price levels and can go
  negative deep in history. **Default choice for indicator work.**
- **Ratio-adjusted:** multiply by the roll ratio. Preserves *returns*, distorts differences.
  Better when computing percentage returns.
- **Unadjusted (stitched):** raw prices with jumps at rolls. Only for execution reference, never for
  indicators — the roll gaps create fake signals.

Roll rules: volume crossover, open-interest crossover, or fixed days before expiry. Volume crossover
is the most common and the most defensible. Whatever you pick, the choice goes in config and in the
snapshot manifest, because it materially changes backtest results.

Never let roll adjustment leak future information: the adjustment applied to a historical bar must be
computable from data available at that bar, or the series must be rebuilt as-of each backtest date.
This is subtle and is a known source of inflated backtest performance.

## Step 6 — verification before declaring the dataset ready
- Round-trip: write → read → assert frame equality
- Row counts match between Parquet and QuestDB
- Spot-check 10 random bars against the raw vendor file by hand
- Confirm the feature pipeline correctly *refuses* an unavailable feature on this dataset
