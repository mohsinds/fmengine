---
name: backtest-review
description: Use when reviewing, reporting, or interpreting any backtest, sweep, or campaign result in fmtrader. Defines the mandatory reporting format, the gates a result must clear, and how to talk about performance honestly.
---

# Reviewing a backtest result

## The core problem this guards against
A 1-minute gold dataset spanning ~5.5 years contains roughly two million bars. A parameter sweep can
evaluate thousands of configurations against it in minutes. Under those conditions, **finding a
config with a high in-sample Sharpe is guaranteed** — it happens with random signals. The Sharpe
ratio alone carries almost no information. Everything below exists to recover the information it lost.

## Mandatory report block

No result is reported without all of this:

```
Strategy / config:        <name + params>
Dataset:                  <dataset_id> @ <content_hash[:12]>
Code:                     <git sha>  Seed: <n>
Period:                   <start> → <end>   Bars: <n>   Trades: <n>

GROSS      Sharpe: __  Sortino: __  CAGR: __  MaxDD: __ (__ days)
NET (1.0x) Sharpe: __  Sortino: __  CAGR: __  MaxDD: __ (__ days)
NET (1.5x) Sharpe: __      NET (2.0x) Sharpe: __
Cost drag: __% of gross P&L     Turnover: __     Exposure: __%

Hit rate: __%   Profit factor: __   Expectancy/trade: __   Avg win/loss: __
Tail ratio: __  Ulcer index: __

Trials in registry: __     Deflated Sharpe Ratio: __     PBO (CSCV): __
Regime breakdown:  2021 __ | 2022 __ | 2023-24 __ | 2025-26 __
Holdout consumed:  yes/no  (if yes: date, result, and note that it is now spent)
Lane:              vectorbt / nautilus   Parity checked: yes/no
```

## Gates — a result that fails any of these is not "promising"

| Gate | Threshold | Meaning of failure |
|---|---|---|
| Net Sharpe at 1.5× costs | > 0 and meaningfully positive | The edge is inside the spread |
| Cost drag | reported, and sanity-checked | If gross ≫ net, you're modeling a strategy that can't trade |
| Deflated Sharpe Ratio | > 0 after trial-count correction | The result is explainable by search effort alone |
| PBO | < 0.5 | The selection procedure itself is overfitting |
| Trade count | high enough for the horizon | Scalping with 40 trades total proves nothing |
| Regime consistency | positive in ≥ 2 regimes, or explicitly labeled regime-specific | A 2022-only artifact |
| Top-trade sensitivity | survives removal of top 5 trades | P&L is a handful of lucky outliers |
| Parameter neighborhood | neighbors perform similarly | A knife-edge optimum is noise |

## Robustness checks to run on anything that passes the gates
- **Parameter surface:** plot/report performance across the neighborhood. Look for a plateau, not a spike.
- **Top-trade removal:** strip the best 5 trades, re-report. Large collapse = outlier dependence.
- **Session split:** Asia / London / NY. An edge concentrated in one session is a real finding worth
  knowing, but changes deployment.
- **Randomization test:** shuffle signal timing while preserving trade frequency, re-run many times,
  and check where the real result sits in that null distribution. This is the most direct answer to
  "is this luck?"
- **Bar-boundary sensitivity:** shift the bar grid by 15/30 seconds. Real edges shouldn't vanish.

## How to write the verdict

State one of: `NOISE` · `FRAGILE` · `CANDIDATE` · `VALIDATED`.

- `CANDIDATE` means it passed the gates on non-holdout data and is worth a fidelity-lane run.
- `VALIDATED` requires a passed fidelity-lane run **and** one holdout evaluation, and that holdout is
  now permanently spent for this strategy.

Never inflate a verdict. If a result is interesting but the trade count is thin, say "interesting but
statistically thin" rather than "promising". The user is making capital-allocation decisions from
these reports.
