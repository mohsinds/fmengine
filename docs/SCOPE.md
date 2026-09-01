# fmengine — Project Scope & Module Charter

**Product:** `fmtrader` (FinnMetrics — https://finnmetrics.com)
**Repository:** `fmengine`
**Owner:** Mohsin — Dimensional Sys, Inc.
**Status:** Living document. Update it when scope changes; do not let code drift from it silently.
**Last revised:** 2026-08-31

---

## Table of contents

1. [Purpose & vision](#1-purpose--vision)
2. [What this is and is not](#2-what-this-is-and-is-not)
3. [Scope boundaries](#3-scope-boundaries)
4. [Architectural invariants](#4-architectural-invariants)
5. [System architecture](#5-system-architecture)
6. [Module registry](#6-module-registry)
7. [Data scope](#7-data-scope)
8. [Analytics & strategy scope](#8-analytics--strategy-scope)
9. [Machine learning scope](#9-machine-learning-scope)
10. [Agentic research scope](#10-agentic-research-scope)
11. [Risk & execution scope](#11-risk--execution-scope)
12. [Non-functional requirements](#12-non-functional-requirements)
13. [Roadmap & exit criteria](#13-roadmap--exit-criteria)
14. [Extension playbooks](#14-extension-playbooks)
15. [Risk register](#15-risk-register)
16. [Glossary](#16-glossary)
17. [Decision log](#17-decision-log)
18. [Open questions](#18-open-questions)

---

## 1. Purpose & vision

`fmengine` is a quantitative research and execution platform. Its purpose is to take a trading
hypothesis from idea to validated, cost-realistic, statistically defensible conclusion — and, when a
strategy earns it, to trade that strategy live through the same code path it was validated on.

**Long-term intent:** the analytical backbone for FinnMetrics, extensible to portfolio management
services. That end state imposes requirements now: auditability, reproducibility, and a risk layer
that exists independently of strategy code.

**The problem the platform actually solves.** Building a backtester is not hard. Building one that
does not lie to you is. A 1-minute gold series over five years is roughly two million bars; a sweep
can evaluate tens of thousands of configurations against it in an afternoon. Under those conditions a
high in-sample Sharpe ratio is not evidence of anything — random signals produce them routinely. Most
of this platform's complexity exists to distinguish a real edge from a search artifact.

---

## 2. What this is and is not

### It is
- A research environment for systematic strategy discovery across multiple asset classes
- A two-lane backtesting engine: fast triage plus high-fidelity event-driven validation
- A statistical validation subsystem that corrects for search effort
- An agent-assisted, long-running hypothesis refinement loop with hard budget control
- A risk and execution layer with backtest → paper → live code parity

### It is not
- A discretionary charting or manual trading tool
- A signal subscription service or a black box that emits buy/sell calls
- A high-frequency / co-located / microsecond-latency system (explicitly out of scope — see §3)
- A replacement for a broker, clearing firm, or custodian
- A regulated advisory product in its current form

### Trading style targeted
**Scalping to short-horizon systematic**: holding periods from seconds to roughly 30 minutes, dozens
to low-hundreds of trades per instrument per day. Latency requirements are ordinary cloud/VPS grade
(tens to hundreds of milliseconds). The binding constraint at this horizon is **cost drag**, not
speed — spread, commission, and slippage consume a large fraction of per-trade edge, and the platform
treats honest cost modeling as a first-class correctness concern.

---

## 3. Scope boundaries

### In scope — now
- Gold (XAUUSD, Dukascopy 1-minute bars) as the first instrument
- Data ingestion, quality gating, canonical storage, dataset snapshots
- Technical indicator library, feature store, labeling
- Two-lane backtesting with realistic cost models
- Validation and anti-overfitting subsystem
- Agentic research campaigns with durable, pausable orchestration
- Risk sizing and limits

### In scope — planned
- CME GC / MGC gold futures (real volume, open interest, contract rolls)
- Silver (SI), copper (HG) and other CME metals
- US equities with point-in-time fundamentals
- Crypto (spot and perpetuals)
- FX
- Optional sentiment and news feature providers
- Multi-asset portfolio construction
- Broker integrations for paper and live execution
- The Next.js review UI (§6.15) — the disposable internal Streamlit script used earlier is not a prototype of it and shares no code with it

### Out of scope — deliberately
| Excluded | Reason |
|---|---|
| Co-located / FPGA / kernel-bypass HFT | Requires exchange colocation, direct binary feeds, and capital far beyond this project. Competing there against established firms is not a winnable game at this scale |
| Options strategies and Greeks | Different pricing, risk, and data model. Would be a separate program of work, not an increment |
| Market making | Different risk profile and infrastructure requirements |
| Client-facing regulated advisory features | No RIA/CTA registration currently planned. Architecture keeps the door open; the features do not exist |
| Manual discretionary trading UI | Not the product |
| Proprietary data redistribution | Licensing constraints from vendors |

### Explicitly deferred, not rejected
Order-book microstructure features, Hawkes-process trade-arrival modeling, and Random Matrix Theory
portfolio construction. All three are legitimate; none are usable on the current dataset (the first
two need tick/trade data, the third needs a multi-asset universe). Seams are built now; implementations come later.

---

## 4. Architectural invariants

These are the rules that make the system extensible. Violating one is not a shortcut — it is a defect.

1. **One canonical data contract.** Every vendor, asset class, and timeframe normalizes to a single
   bar schema before touching anything downstream. Adding an asset class means adding an *adapter*.
   If core code must change to support a new instrument, the abstraction was wrong.

2. **Two backtest lanes, never one.** vectorbt triages; NautilusTrader validates. Nothing is declared
   working on the fast lane alone — vectorized backtests are fast precisely because they abstract away
   the microstructure that determines whether a scalping strategy is tradable.

3. **No LLM in the live path.** Language models live in the offline research tier only. They never sit
   between a market data event and an order. Rationale: latency, non-determinism, and the requirement
   that live P&L be attributable and reproducible.

4. **Reproducibility is enforced, not encouraged.** Every result carries dataset content hash, config
   hash, git SHA, and seed. Results lacking them are rejected at write time.

5. **Risk sits between signal and execution.** Position sizing, limits, and kill-switches are a
   separate service, never embedded in strategy code. This is what makes the risk layer auditable
   and what allows a single kill-switch to govern every strategy.

6. **The holdout vault is sacred.** The most recent ~12 months of every dataset is unreadable through
   normal code paths. Unlocking requires an explicit token, is logged, and is irreversible per
   strategy. One evaluation per strategy, ever.

7. **Fail loudly.** Silent NaN propagation, silent empty frames, and swallowed exceptions are
   forbidden. A feature requested on a dataset that cannot support it raises an error naming the
   dataset and the missing capability.

8. **Config over constants.** Anything that changes results lives in typed configuration, not in code.

---

## 5. System architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  PRESENTATION        Next.js UI (Ph.11) · FastAPI · Temporal UI ·      │
│                      MLflow · research journal (Markdown)             │
├──────────────────────────────────────────────────────────────────────┤
│  ORCHESTRATION       Temporal workflows · durable campaigns ·         │
│                      pause/resume/abort signals · checkpointing       │
├──────────────────────────────────────────────────────────────────────┤
│  AGENTIC RESEARCH    LangGraph loop · LLM router (local/frontier) ·   │
│  (Tier 2, offline)   budget governor · journal · search-space evolution│
├──────────────────────────────────────────────────────────────────────┤
│  VALIDATION          purged CV · walk-forward · trial registry ·      │
│  ★ correctness core  DSR · PBO/CSCV · holdout vault · leakage tests   │
├──────────────────────────────────────────────────────────────────────┤
│  BACKTEST            vectorbt lane (triage) │ NautilusTrader lane      │
│                      cost models · metrics · parity checks             │
├──────────────────────────────────────────────────────────────────────┤
│  RISK                fractional Kelly · vol targeting · conformal gate │
│                      limits · kill-switches · portfolio construction   │
├──────────────────────────────────────────────────────────────────────┤
│  STRATEGY            engine-agnostic base · registry · search-space DSL│
├──────────────────────────────────────────────────────────────────────┤
│  MODELS              GBM baseline · calibration · conformal · Bayesian │
│  (Tier 1, live-safe) deterministic, compiled, no network calls         │
├──────────────────────────────────────────────────────────────────────┤
│  FEATURES            indicators · regime · labeling · feature store ·  │
│                      optional providers (sentiment, fundamentals)      │
├──────────────────────────────────────────────────────────────────────┤
│  DATA                adapters · ingestion · quality gate · catalog ·   │
│                      snapshots · contract rolls · session calendars    │
├──────────────────────────────────────────────────────────────────────┤
│  EXECUTION           broker adapters · paper · live · reconciliation   │
├──────────────────────────────────────────────────────────────────────┤
│  INFRASTRUCTURE      QuestDB · Postgres · Redis · Temporal · MLflow ·  │
│                      Ollama · Parquet catalog                          │
└──────────────────────────────────────────────────────────────────────┘
```

**The AI tier separation is load-bearing.** Tier 1 (models that can influence orders) is
deterministic, compiled, offline-capable, and testable. Tier 2 (agentic research) is non-deterministic,
network-dependent, and structurally incapable of reaching the live path. These tiers never merge.

---

## 6. Module registry

Status legend: `PLANNED` · `IN PROGRESS` · `BUILT` · `DEFERRED` · `BLOCKED`

### 6.1 `core` — domain contracts
| | |
|---|---|
| **Purpose** | Canonical types every other module depends on |
| **Owns** | `Bar` schema, enums (`instrument_class`, `timeframe`, `order_type`, `side`), error hierarchy, correlation-ID types |
| **Depends on** | Nothing. This module has zero internal dependencies by design |
| **Must not** | Contain business logic, IO, or vendor-specific concepts |
| **Phase** | 1 · **Status:** `PLANNED` |

### 6.2 `config` — typed configuration
| | |
|---|---|
| **Purpose** | Single source of truth for every parameter that affects results |
| **Owns** | pydantic-settings trees, YAML loading, env overlay, config hashing |
| **Key rule** | If a value changes a backtest result, it lives here and is included in the config hash |
| **Phase** | 1 · **Status:** `PLANNED` |

### 6.3 `data` — ingestion, storage, quality
| | |
|---|---|
| **Purpose** | Turn any vendor format into trustworthy canonical bars |
| **Submodules** | `adapters/` · `ingest` · `quality` · `catalog` · `resample` · `contracts` (futures rolls) · `calendars` |
| **Owns** | Vendor normalization, quality gates, Parquet catalog, snapshot manifests, QuestDB mirror, continuous-contract construction |
| **Must not** | Compute indicators, filter data on undocumented heuristics, or impute missing values silently |
| **Extension point** | New vendor = new adapter + capability declaration. No core changes |
| **Phase** | 2 · **Status:** `PLANNED` |

### 6.4 `features` — indicators, regime, labeling
| | |
|---|---|
| **Purpose** | Derive model- and strategy-ready features from canonical bars |
| **Submodules** | `indicators/` (trend, momentum, volatility, volume, microstructure, session) · `regime` · `labeling` · `pipeline` · `store` |
| **Owns** | Indicator registry with capability declarations, triple-barrier labeling, meta-labeling, sample weighting, versioned feature store |
| **Key rule** | Every indicator declares its data requirements. Requesting a volume feature on a volume-less dataset raises — it does not return NaN |
| **Phase** | 3 · **Status:** `PLANNED` |

### 6.5 `strategy` — definition and search space
| | |
|---|---|
| **Purpose** | Define strategies once, run them in both backtest lanes and in live |
| **Owns** | Engine-agnostic `Strategy` base, registry, parameter schemas, search-space DSL, strategy library |
| **Must not** | Contain risk sizing, position limits, or broker-specific logic |
| **Phase** | 3–4 · **Status:** `PLANNED` |

### 6.6 `backtest` — two lanes, costs, metrics
| | |
|---|---|
| **Purpose** | Evaluate strategies fast, then evaluate survivors honestly |
| **Submodules** | `vbt/` (triage) · `nautilus/` (fidelity) · `costs` · `metrics` · `validation/` |
| **Owns** | Sweep execution, chunking, worker pool, cost models (spread/commission/slippage), full metric suite, lane parity checks |
| **Key rule** | Every reported result includes net-of-cost metrics and cost drag as a percentage of gross P&L |
| **Phase** | 4 · **Status:** `PLANNED` |

### 6.7 `validation` — the correctness core ★
| | |
|---|---|
| **Purpose** | Distinguish real edges from search artifacts. The single most important module |
| **Owns** | Purged/embargoed K-fold, walk-forward (rolling + anchored), regime segmentation, trial registry, Deflated Sharpe Ratio, PBO via CSCV, holdout vault + token guard, leakage test suite |
| **Key rule** | Every evaluated configuration is written to the trial registry. The trial count is the denominator for every multiple-testing correction |
| **Built before** | Any agentic campaign is permitted to run |
| **Phase** | 5 · **Status:** `PLANNED` |

### 6.8 `models` — Tier 1, live-safe ML
| | |
|---|---|
| **Purpose** | Deterministic predictive models that may influence orders |
| **Owns** | GBM training (LightGBM/XGBoost), probability calibration (Platt/isotonic), split-conformal uncertainty, Bayesian baseline, model serialization |
| **Must not** | Make network calls, invoke an LLM, or depend on non-deterministic inputs |
| **Key rule** | Probabilities feeding position sizing must be calibrated. Uncalibrated probabilities make Kelly sizing dangerous |
| **Phase** | 5–8 · **Status:** `PLANNED` |

### 6.9 `risk` — sizing, limits, kill-switches
| | |
|---|---|
| **Purpose** | Convert a signal into a position size, or refuse to |
| **Owns** | Fractional Kelly (default 0.25), volatility targeting, fixed-fractional sizing, conformal uncertainty gate, per-trade / daily / drawdown limits, consecutive-loss breaker, kill-switch |
| **Position** | Structurally between signal and execution. Never inside strategy code |
| **Deferred** | RMT / Ledoit-Wolf correlation cleaning — requires multi-asset universe |
| **Phase** | 8 · **Status:** `PLANNED` |

### 6.10 `agents` — Tier 2, offline research
| | |
|---|---|
| **Purpose** | Propose, critique, and refine strategy hypotheses across generations |
| **Owns** | LangGraph loop, node implementations (hypothesize / validate / evaluate / critique / select), LLM router, budget governor, cost ledger, research journal |
| **Must not** | Read the holdout, write to the trial registry directly, emit executable code, or influence live execution |
| **Key rule** | Agents propose **structured configs against a declared schema**, which trusted code validates and instantiates. Never free-form Python |
| **Depends on** | Module 6.7 `validation` (built first, no exception) · may consume module 6.13 `sentiment`/6.14 `fundamentals` features once registered |
| **Phase** | 7 · **Status:** `PLANNED` |

### 6.11 `orchestration` — durable execution
| | |
|---|---|
| **Purpose** | Run week-long campaigns that survive restarts and support pause/resume |
| **Owns** | Temporal workflows and activities, signal handlers (`pause`, `resume`, `adjust_budget`, `abort`), per-generation checkpointing, worker process |
| **Phase** | 7 · **Status:** `PLANNED` |

### 6.12 `execution` — brokers and live trading
| | |
|---|---|
| **Purpose** | Route validated strategies to paper and live venues |
| **Owns** | `BrokerAdapter` interface, IBKR adapter, paper harness, order reconciliation, idempotent client order IDs, independent kill-switch |
| **Key rule** | Paper and live use the identical strategy code path as backtest. Divergence is a defect |
| **Phase** | 10 · **Status:** `PLANNED` |

### 6.13 `sentiment` — pluggable feature provider (framework now, sources later)
| | |
|---|---|
| **Purpose** | News and sentiment as optional, pluggable features, via the shared `FeatureProvider` protocol |
| **Owns** | The point-in-time record contract, as-of join engine, alignment strategies, and a `SyntheticNewsProvider` for testing the join semantics. See `PROVIDER_ARCHITECTURE.md` |
| **Key rule** | A record is usable at bar `t` only if its **`available_time`** precedes `t` — never `event_time`. Revision leakage is a silent, severe bias |
| **Optionality** | The core engine must run fully without any concrete provider installed or configured |
| **Phase** | **6** — protocol, join engine, and synthetic provider are built here, before the agentic pipeline, so Phase 7 can propose sentiment features from its first campaign. A real news/sentiment vendor is a separate, later decision (see open question 7); the framework itself is not deferred. **Status:** `PLANNED` |

### 6.14 `fundamentals` — pluggable feature provider (framework now, equities data later)
| | |
|---|---|
| **Purpose** | Point-in-time fundamental data for equity strategies, via the same `FeatureProvider` protocol as 6.13 |
| **Key rule** | As-reported only, never restated, enforced via the three-timestamp contract (`event_time` / `available_time` / `ingestion_time`). Using restated figures is a classic look-ahead bias |
| **Phase** | Protocol support ships in **Phase 6** alongside 6.13 (same interface, no separate framework work). Concrete equity fundamentals vendor integration: **Equities phase** · **Status:** `DEFERRED` (vendor selection), framework `PLANNED` |

### 6.15 `api` & `ui` — observability
| | |
|---|---|
| **Purpose** | Make campaign state, results, and reasoning legible to a human |
| **Owns** | FastAPI endpoints (runs, experiments, journal, campaign control), the Next.js review UI, journal Markdown rendering |
| **Design rule** | The UI is a client of the API, never a monolith. The FastAPI contract is frozen at the end of Phase 5 so UI work never blocks on backend churn |
| **Interim tool** | A disposable Streamlit script may be used **internally, Phases 2–5 only**, to eyeball ingestion/feature/backtest output while those layers are being built. It is not tested, not specified, not part of any deliverable, and is deleted once Phase 11 ships. See `FRONTEND_SPEC.md` §3 |
| **Phase** | 11 · **Status:** `PLANNED` |

---

## 7. Data scope

### Asset class roadmap
| Asset class | Instruments | Vendor | Phase | Status |
|---|---|---|---|---|
| Spot gold (CFD) | XAUUSD | Dukascopy (free) | 1–8 | Active |
| CME metals futures | GC, MGC, SI, HG | Databento / Barchart | 9 | Planned |
| US equities | Liquid large-cap universe | Polygon / Databento + fundamentals vendor | Later | Planned |
| Crypto | BTC, ETH spot + perps | CCXT / exchange APIs | Later | Planned |
| FX | Major pairs | Dukascopy / broker feed | Later | Planned |

### Current dataset — known limitations
`download/xauusd-m1-bid-2021-01-01-2026-08-31.csv`, columns `timestamp,open,high,low,close`.

| Limitation | Consequence | Handling |
|---|---|---|
| Epoch **milliseconds**, UTC | Parsing errors if assumed seconds | Explicit conversion; all datetimes tz-aware UTC |
| **No volume column** | VWAP, OBV, MFI, volume profile, cumulative delta, Hawkes intensity all unavailable | Capability gating raises a named error |
| **Bid side only** | Spread unmeasurable | Conservative assumed spread from config; never zero. Download ask side to fix |
| Flat-bar runs (identical OHLC) | No-tick periods — weekends, holidays, thin hours | Detect runs, flag non-tradable, exclude from signal generation |
| Spot CFD ≠ CME futures | No open interest, no roll, synthetic broker quotes, different cost structure | Phase 1–8 results are **pipeline validation, not tradable conclusions**. Re-validate in Phase 9 |

### Storage model
- **Canonical Parquet** partitioned `symbol/timeframe/year=YYYY/month=MM` — the source of truth
- **QuestDB** — query and exploration mirror
- **NautilusTrader ParquetDataCatalog** — fidelity lane input
- **Snapshot manifests** (`data/snapshots/*.json`) — content hash, provenance, capability flags, quality report

### Data quality gate
**Hard-fail:** non-monotonic or duplicate timestamps · OHLC invariant violations (`low ≤ min(open, close)`,
`high ≥ max(open, close)`, all positive) · impossible values.
**Report:** gaps classified against the session calendar (weekend / holiday / rollover / anomalous) ·
MAD-based return outliers · flat-bar run counts · monthly coverage table.

### Futures-specific scope (Phase 9)
Continuous-contract construction supporting back-adjusted (Panama), ratio-adjusted, and unadjusted
series; roll rules by volume crossover, open-interest crossover, or fixed days-to-expiry. Raw
per-contract data retained alongside — a continuous contract is a research construct and cannot be
traded. Roll adjustment must not leak future information into historical bars.

---

## 8. Analytics & strategy scope

### Indicator taxonomy
| Category | Members | Data requirement |
|---|---|---|
| **Trend** | SMA, EMA, WMA, HMA, DEMA/TEMA, ADX/DMI, Aroon, Supertrend, linear-regression slope, Ichimoku | OHLC |
| **Momentum** | RSI (incl. short-period RSI(2)/RSI(7) for scalping), Stochastic, CCI, Williams %R, ROC, MACD + histogram slope, TSI | OHLC |
| **Volatility** | ATR & normalized ATR, Bollinger Bands + %B + bandwidth/squeeze, Keltner, Donchian, Chaikin volatility, Parkinson, Garman-Klass, Rogers-Satchell, Yang-Zhang, quantile volatility regime | OHLC |
| **Volume** | VWAP + bands, anchored VWAP, OBV, MFI, volume profile / POC, cumulative delta | **Volume — unavailable on current dataset** |
| **Microstructure** | Order-book imbalance, trade-arrival intensity, Hawkes clustering, spread dynamics | **Tick/L2 — Phase 9+** |
| **Session/time** | Minute-of-day, session bucket (Asia/London/NY), time-since-open, day-of-week, macro-release proximity | Timestamp |
| **Cross-asset** | Gold/silver ratio, gold/copper ratio, DXY, real yields | Multi-instrument — later |

### Statistical methods — assessment and placement
| Method | Verdict | Placement |
|---|---|---|
| **Quantile volatility regime** | Use now. Cheap, robust, genuinely informative | Phase 3, `features/regime` |
| **Conformal prediction filter** | Use. The sharpest tool here — implements "high probability but high uncertainty → skip or shrink" | Phase 8, `models/conformal` + `risk` |
| **Fractional Kelly sizing** | Use, at ~0.25 fraction. Full Kelly is too aggressive for real deployment | Phase 8, `risk/sizing` |
| **Probability calibration** | Prerequisite for Kelly, not an optional refinement. Uncalibrated inputs make Kelly actively dangerous | Phase 5–8, `models/calibrate` |
| **Bayesian classifier** | Acceptable baseline; gradient-boosted trees will likely outperform. The value is calibrated probabilities, not Bayes specifically | Phase 5, `models/bayes` |
| **Hawkes process** | `BLOCKED` — requires trade/tick arrival data. Cannot run on volume-less 1-minute bars | Phase 9+ |
| **Random Matrix Theory / Ledoit-Wolf** | `DEFERRED` — meaningless on a single instrument | Multi-asset phase, `risk/portfolio` |
| **Deflated Sharpe Ratio, PBO/CSCV** | **Mandatory.** The most important addition to the analytics scope given the planned scale of automated search | Phase 5, `validation` |

### Labeling
Triple-barrier method with ATR-scaled profit-take, stop-loss, and time barriers. Meta-labeling: a
primary rule determines side, a secondary model decides whether to take the trade — historically where
ML contributes most. Sample weights derived from label uniqueness to prevent overlapping outcomes
from inflating effective sample size.

### Cost modeling
Per-instrument, per-session: spread (measured where bid/ask exist, conservative constant otherwise,
widening off-session), commission (per-contract or per-notional), slippage (base plus volatility-scaled,
differentiated by order type), and funding/roll costs. **Mandatory sensitivity sweep at 1.0×, 1.5×,
and 2.0×.** A strategy whose edge dies at 1.5× costs is marked `fragile` and does not proceed.

---

## 9. Machine learning scope

### Tier 1 — live-safe models
Deterministic, compiled, offline. Gradient-boosted trees (LightGBM/XGBoost) as the primary baseline;
sequence models (LSTM, temporal CNN, small transformers) only if trees plateau **and** there is a
specific hypothesis about sequential structure they are missing. Every model that can influence a
position must be calibrated and must expose an uncertainty estimate.

### Tier 2 — research models
Local LLMs via Ollama (bulk hypothesis generation, mutation, summarization) and frontier APIs
(Claude, OpenAI, Gemini) for gating decisions only. Never in the live path, under any framing.

### Validation requirements for every model
Purged and embargoed cross-validation · walk-forward evaluation · regime-segmented reporting ·
feature-importance stability across folds · calibration curves · registration in the trial registry.

### Explicitly out of scope
Reinforcement learning for direct order placement (sample efficiency and safety properties are poor
for this problem at this capital scale); deep learning on raw price series without feature engineering;
any model whose predictions cannot be explained well enough to diagnose a live failure.

---

## 10. Agentic research scope

### Campaign model
A campaign runs for days to weeks as a Temporal workflow, iterating generations:

```
hypothesize → validate proposals → fast sweep (vectorbt) → shortlist (net metrics + DSR gate)
   → fidelity run (NautilusTrader) → critique → select survivors + next search space
   → journal → checkpoint
```

### Capabilities
Pause, resume, abort, and budget adjustment via signals · survives machine sleep and restarts ·
per-generation durable checkpoints · parallel evaluation within the worker budget · full state
visible in the Temporal UI.

### Hard constraints on agent behavior
| Constraint | Enforcement |
|---|---|
| Cannot read the holdout vault | Code-level token guard, not prompt instruction |
| Cannot write to the trial registry directly | Only validated activities write |
| Cannot emit executable code | Proposals are structured configs validated against a schema |
| Cannot influence live execution | No code path exists from Tier 2 to execution |
| Cannot exceed budget | Pre-call cost estimation, three-level caps, refusal on breach |
| Cannot weaken validation gates | Gates live outside agent-reachable code |

### Budget governance
Hard USD caps per campaign, per generation, per day, and per provider. Every call is ledgered
(provider, model, tokens, cost, purpose, campaign). On exhaustion the campaign degrades gracefully to
local models and continues rather than crashing or overspending.

### The research journal
Per generation: hypothesis, exact parameters tried, net-of-cost metrics with trial count and DSR,
survivors and the reasoning behind their selection, the next search space and why, and cumulative
spend. This is the primary human-readable artifact of a campaign and is written for a reader who was
not watching it run.

---

## 11. Risk & execution scope

### Risk layer responsibilities
Position sizing (fractional Kelly, volatility targeting, fixed-fractional) · uncertainty gating via
conformal intervals · per-trade, daily, and drawdown loss limits · maximum position and trade-count
limits · consecutive-loss circuit breaker · a kill-switch reachable independently of the strategy
process.

### Execution scope
| Capability | Phase | Notes |
|---|---|---|
| Backtest execution simulation | 4 | Both lanes |
| Paper trading | 10 | Identical code path to backtest |
| Live trading | Post-validation | Hard capital limits at first deployment |
| Broker: IBKR | 10 | First adapter — existing Pro account |
| Broker: futures-specialist (Tradovate/Rithmic) | Later | If execution quality warrants |
| Broker: crypto via CCXT | Later | |
| Multi-venue smart order routing | Out of scope for now | |

### Live deployment gate
A strategy reaches live capital only after: passing all validation gates on non-holdout data ·
a clean fidelity-lane run · a red-team review with no unresolved critical findings · one holdout
evaluation · a sustained paper-trading period · and explicit human approval. No automated promotion
from research to live capital exists, by design.

---

## 12. Non-functional requirements

### Hardware envelope (current development machine)
Apple M5 Pro · 15 cores (5 efficiency, 10 performance) · 16-core GPU · **24 GB unified memory** · 1 TB SSD.

Memory is the binding constraint. Budget:
| Consumer | Ceiling |
|---|---|
| Docker stack (QuestDB, Postgres, Temporal, Redis, MLflow) | 6 GB |
| Ollama local inference | 8 GB |
| Backtest worker pool (6 workers default) | 6 GB |
| macOS, IDE, headroom | 4 GB |

Only one 14B model resident at a time, never during a large sweep. The LLM router checks available
memory before loading and falls back to a 7B model under pressure.

### Performance targets
| Operation | Target |
|---|---|
| Ingest 5 years of 1-minute bars | < 5 minutes |
| Full feature build (~2M bars, ~50 features) | < 10 minutes, within memory budget |
| vectorbt sweep, 1,000 configs | < 15 minutes on 6 workers |
| NautilusTrader fidelity run, single config, 5 years | < 10 minutes |
| Live signal generation (Tier 1, future) | < 50 ms feature-to-signal |

### Reproducibility
Every artifact records dataset content hash, config hash, git SHA, seed, and timestamp. A result
without complete provenance is rejected at write time. A backtest from six months ago must be
re-runnable to identical output.

### Observability
structlog JSON logging with `run_id` / `campaign_id` correlation · MLflow for run tracking and
comparison · Temporal UI for campaign state · the Next.js review UI (Phase 11, `FRONTEND_SPEC.md`)
for results and journal rendering. A disposable, unspecified Streamlit script may be used internally
during Phases 2–5 to eyeball intermediate output — see §6.15 — but it is not this deliverable.

### Security
Credentials in `.env` and never committed · broker credentials never in agent-reachable context ·
LLM API keys scoped and budget-capped · no PII in this system · the kill-switch must function
independently of the main application process.

---

## 13. Roadmap & exit criteria

This is the single canonical phase numbering for the project. Every other document
(`SETUP_PROMPT.md`, `BUILD_PLAN.md`, `PROVIDER_ARCHITECTURE.md`, `FRONTEND_SPEC.md`) uses these same
eleven numbers. If a document appears to disagree, the document is wrong and this table is the
tiebreaker — see the maintenance note at the end of this file.

| Phase | Scope | Exit criteria |
|---|---|---|
| **1. Foundation** | Repo scaffolding, Docker stack, Ollama, tooling, CI | `make up && make check` green; all service UIs load |
| **2. Data** | Contracts, Dukascopy adapter, quality gate, catalog, snapshots | Gold ingested; coverage table printed; Parquet/QuestDB counts reconcile; 10 bars hand-verified |
| **3. Features** | Indicators, regime, labeling, feature store | All indicator + property tests pass; full build inside memory budget; volume request on this dataset raises |
| **4. Backtest + Execution Recorder** | Two lanes, cost models, metrics, provenance capture | Buy-and-hold nets identical across lanes within tolerance; planted look-ahead strategy caught; every run writes a complete manifest |
| **5. Validation ★** | Purged CV, walk-forward, trial registry, DSR, PBO, holdout vault | Every planted leakage bug caught; noise-calibration sweep returns `NOISE`; holdout guard proves the vault unreadable via normal paths |
| **6. Provider framework** | `FeatureProvider` protocol, point-in-time contract, as-of join engine, `SyntheticNewsProvider` | Core pipeline runs unchanged with zero providers registered; planted `event_time` join is caught; property test proves future records never change past feature values |
| **7. Agentic** | Temporal workflows, LangGraph loop, budget governor, journal | 24h campaign runs; paused mid-generation; machine restarted; resumes correctly; journal explains every decision |
| **8. Risk** | Kelly, vol targeting, conformal gate, limits, kill-switch | Sizing tests pass; conformal gate rejects high-uncertainty signals; kill-switch halts on breach |
| **9. CME futures** | Databento adapter, rolls, real volume, microstructure unlock | GC/MGC ingested with OI; continuous series validated; surviving strategies re-validated on futures data |
| **10. Execution** | Broker adapters, paper trading, reconciliation | Paper trades execute on the identical code path; reconciliation survives a forced disconnect |
| **11. Observability & UI** | FastAPI (contract frozen at end of Phase 5), Next.js review app, journal rendering | Campaign state, results, and reasoning legible without reading logs; win rate never renders without expectancy beside it |
| **Later** | Concrete news/sentiment vendor, equities + fundamentals vendor, crypto, FX, multi-asset portfolio | Per-vendor criteria defined when a vendor is selected — see open question 7 |

**Sequencing rules, in order of strictness:**
1. **Phase 5 before Phase 7, without exception.** An agent turned loose on an unvalidated backtest
   harness is an efficient generator of expensive false confidence.
2. **Phase 6 before Phase 7, recommended but not hard-blocking.** Building the provider framework
   first means the agent can propose sentiment/fundamentals feature sets from its very first
   campaign. Doing it in the other order is possible but means a mid-project redesign of the search
   space once providers arrive.
3. Phases 9, 10, and 11 have no ordering constraint against each other — sequence them by whichever
   unblocks the next decision you actually need to make.

---

## 14. Extension playbooks

### Adding an asset class
1. Write the vendor adapter with a full capability declaration
2. Extend the session calendar registry
3. Implement roll/adjustment logic if applicable (futures) or corporate actions (equities)
4. Run the quality gate; commit the snapshot manifest
5. Document which features and strategies become newly available or newly unavailable
6. Re-validate existing strategies — **expect results to change**

*No core module should require modification. If one does, raise it as an architecture defect.*

### Adding a data vendor
Capability audit → adapter → capability declaration → quality gate → integration tests (schema
conformance, timezone correctness, gap classification, round-trip equality) → snapshot manifest.

### Adding an indicator
Pure vectorized function → registry entry with data requirements and `min_lookback` → parameter schema
→ four mandatory tests (correctness against reference, warmup/no-look-ahead, degenerate input,
property invariant). See `.cursor/skills/indicator-implementation/SKILL.md`.

### Adding a strategy
State the hypothesis including its expected failure regime → check data requirements against the
dataset manifest → implement against the engine-agnostic base → declare parameter schema and search
space → register → adapt for both lanes → tests including cross-lane parity → small sweep with
net-of-cost reporting. See `.cursor/commands/new-strategy.md`.

### Adding a broker
Implement `BrokerAdapter` (connect, subscribe, submit/modify/cancel, positions, account, reconcile) →
idempotent client order IDs → reconciliation on reconnect → paper validation before live → confirm
the kill-switch reaches it independently.

### Adding a feature provider (sentiment, fundamentals, alternative data)
Implement the `FeatureProvider` protocol from Phase 6 → declare capabilities and `PointInTimeRecord`
semantics → choose alignment strategies per feature → guarantee point-in-time correctness via
`available_time`, never `event_time` → ensure the core engine runs unchanged when the provider is
absent → gate features on provider availability → run the paired with/without campaign comparison
before drawing any conclusion about the provider's value. Full spec: `PROVIDER_ARCHITECTURE.md`.
This adds a new adapter and a new YAML block only — no changes to the pipeline, backtest engine,
validation layer, or UI. If it forces such a change, the abstraction has a hole in it.

---

## 15. Risk register

| Risk | Severity | Mitigation | Owner phase |
|---|---|---|---|
| Automated search produces spurious edges at scale | **Critical** | Trial registry, DSR, PBO, locked holdout — built before any agent runs | 5 |
| Look-ahead bias in features or fills | **Critical** | Leakage test suite with planted bugs; `/leak-audit` before trusting any result; red-team review | 4–5 |
| Scalping edge lies entirely inside the spread | High | Net-of-cost reporting always; 1.5×/2.0× sensitivity as a hard gate; cost drag reported | 4 |
| Bid-only, volume-less data misleads assumptions | High | Capability gating raises loudly; acquire ask side; conservative spread constant; re-validate on CME data | 2, 9 |
| XAUUSD results fail to transfer to GC futures | Medium | Treat Phases 1–8 as pipeline validation, not tradable conclusions | 9 |
| 24 GB memory contention | Medium | Explicit budgets, capped containers, pre-load memory checks, configurable workers | 1 |
| LLM API overspend on a long campaign | Medium | Pre-call estimation, three-level caps, ledger, graceful degradation | 7 |
| Campaign lost to restart or sleep | Medium | Temporal durable execution with per-generation checkpoints | 7 |
| Provider join uses publication time instead of availability time | **Critical** | As-of join engine keys exclusively on `available_time`; planted-leakage and property tests in Phase 6 | 6 |
| Scope sprawl across asset classes | Medium | One instrument working end-to-end before adding a second; adapters at the edges | Ongoing |
| Live/backtest behavioral divergence | High | Single code path across lanes and live; parity tests; paper period before capital | 10 |

---

## 16. Glossary

**Adverse selection** — being filled specifically because the market is about to move against you.
**Anchored VWAP** — VWAP computed from a chosen anchor point rather than session start.
**Back-adjusted (Panama)** — continuous futures series built by cumulatively subtracting roll gaps; preserves price differences, distorts absolute levels.
**Backwardation** — futures curve sloping downward; near contracts priced above deferred.
**Basis** — difference between spot and futures price.
**Contango** — futures curve sloping upward; deferred contracts priced above near.
**Cost drag** — proportion of gross P&L consumed by spread, commission, and slippage.
**CSCV** — Combinatorially Symmetric Cross-Validation; the procedure used to compute PBO.
**Cumulative delta** — running difference between buy-initiated and sell-initiated volume.
**Deflated Sharpe Ratio (DSR)** — Sharpe ratio adjusted for the number of trials that produced it.
**Embargo** — buffer period after a test fold excluded from training to prevent leakage.
**Fractional Kelly** — Kelly-optimal position size scaled by a fraction (commonly 0.25) to reduce variance and model-error sensitivity.
**Hawkes process** — self-exciting point process used to model clustering of trade or order arrivals.
**Holdout vault** — reserved recent data, unreadable by research code, usable once per strategy.
**Look-ahead bias** — using information at time `t` that was not available at time `t`.
**MBO / MBP** — market-by-order (full order-level detail) / market-by-price (aggregated by level).
**Meta-labeling** — a secondary model deciding whether to act on a primary model's signal.
**Open interest** — total outstanding futures contracts; a conviction indicator.
**PBO** — Probability of Backtest Overfitting; the chance the selected configuration underperforms out-of-sample.
**Point-in-time data** — data as it was known at a historical moment, without subsequent restatement.
**Purged K-fold** — cross-validation removing training samples whose label windows overlap the test fold.
**Queue position** — a resting order's place in the FIFO at a price level; determines fill probability.
**Roll yield** — return arising from rolling futures positions along the curve.
**Slippage** — difference between expected and actual fill price.
**Split conformal prediction** — distribution-free method producing prediction intervals with coverage guarantees.
**Tick-to-trade latency** — elapsed time from market data receipt to order transmission.
**Triple-barrier labeling** — labeling by whichever of profit-take, stop-loss, or time barrier is hit first.
**Walk-forward analysis** — repeated train-then-test on rolling or anchored windows moving through time.

---

## 17. Decision log

Architectural decisions with real tradeoffs get a short ADR in `docs/adr/NNNN-title.md`.
Format: context · options considered · decision · consequences · date.

| # | Decision | Rationale |
|---|---|---|
| 0001 | NautilusTrader as the fidelity engine over QuantConnect LEAN | Event-driven with backtest→live code parity, no vendor lock-in, actor/message model aligned with prior production experience |
| 0002 | vectorbt as a triage lane only, never a validation lane | Vectorized backtests abstract away exactly the microstructure that determines scalping viability |
| 0003 | Temporal for campaign orchestration | Durable week-long execution with pause/resume, surviving restarts; existing team familiarity |
| 0004 | Hard Tier 1 / Tier 2 AI separation | LLM latency and non-determinism are incompatible with a live order path; P&L must be attributable |
| 0005 | Polars as the primary dataframe library | Memory efficiency under a 24 GB ceiling; strong arm64 performance |
| 0006 | Validation subsystem built before the agentic loop | An agent on an unvalidated harness manufactures false confidence at scale |
| 0007 | Holdout vault enforced in code, not by convention | Human discipline reliably fails against the temptation to peek |
| 0008 | Start with a single instrument end-to-end | Proves the pipeline before multiplying surface area |
| 0009 | Provider framework (Phase 6) built before the agentic pipeline (Phase 7), ahead of any concrete vendor | Concrete news/fundamentals vendors remain a later, separate decision (open questions 7–8), but the pluggable interface must exist before the agent's search space is designed, or the search space needs a mid-project redesign |
| 0010 | The Next.js app in `FRONTEND_SPEC.md`, not Streamlit, is the only specified UI deliverable | Streamlit is disposable internal tooling for Phases 2–5; specifying two production UIs invited exactly the drift this decision closes off — see resolved open question 4 |

---

## 18. Open questions

| # | Question | Blocks | Status |
|---|---|---|---|
| 1 | Primary broker for paper and live — IBKR, or a futures specialist (Tradovate/Rithmic)? | Phase 10 adapter priority | Open |
| 2 | Weekly USD budget cap for frontier LLM calls | Phase 7 governor configuration | Open |
| 3 | GC ($10/tick) or MGC ($1/tick) as the live target? | Phase 8 position sizing realism | Open |
| 4 | ~~Streamlit sufficient through Phase 5, or is a richer UI needed earlier?~~ | — | **Resolved:** Streamlit is a disposable internal tool for Phases 2–5 only — not tested, not specified, no promotion path. The Next.js app in `FRONTEND_SPEC.md` is the only specified deliverable, built in Phase 11. See §14 extension playbooks note and `FRONTEND_SPEC.md` §3 |
| 5 | Timeline and trigger for acquiring paid CME data | Phase 9 start | Open |
| 6 | Is vectorbt open-source sufficient, or will the Pro version be needed? | Phase 4 — revisit only if the fast lane becomes a measured bottleneck | Deferred |
| 7 | Which sentiment/news vendor, and at what budget? | Concrete provider behind the Phase 6 framework — see `PROVIDER_ARCHITECTURE.md` §5 | Deferred |
| 8 | Which fundamentals vendor for the equities phase, and at what budget? | Concrete provider behind the Phase 6 framework — see `PROVIDER_ARCHITECTURE.md` §6 | Deferred |

---

*Maintenance: revise this document whenever scope, module boundaries, or invariants change. When code
and this document disagree, one of them is wrong — resolve it rather than letting the gap widen.*