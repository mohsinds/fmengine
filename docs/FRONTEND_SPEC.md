# fmtrader — Frontend Specification

**Component:** `fmtrader-web` — control and observability UI for the `fmengine` platform
**Location:** top-level `web/` directory, sibling to `src/fmtrader/` — a separate npm/pnpm project,
not nested inside the Python package. It talks to `src/fmtrader/api` over HTTP/SSE only; nesting a
JS/TS app inside `src/fmtrader/` would fight both ecosystems' tooling. See `SETUP_PROMPT.md` §1 for
the full repo layout.
**Status:** Living document — single source of truth for the UI. This document merges what was
previously two separate files (`FRONTEND_SPEC.md` and `REVIEW_UI_SPEC.md`); the second one produced
a dangling "supersedes §13" reference once it existed on its own with nothing left for it to point
at. There is now exactly one frontend spec, and §21 is its one build order.
**Last revised:** 2026-08-31

---

## Table of contents

1. [Purpose](#1-purpose)
2. [The manual-tuning problem you must not create](#2-the-manual-tuning-problem-you-must-not-create)
3. [Stack decision & build timing](#3-stack-decision--build-timing)
4. [Information architecture](#4-information-architecture)
5. [Screen specifications](#5-screen-specifications)
6. [Real-time model](#6-real-time-model)
7. [API contract](#7-api-contract)
8. [Data model for the UI](#8-data-model-for-the-ui)
9. [Component inventory](#9-component-inventory)
10. [Performance requirements](#10-performance-requirements)
11. [Guard rails enforced in the UI](#11-guard-rails-enforced-in-the-ui)
12. [Design language](#12-design-language)
13. [The Execution Record — the core abstraction](#13-the-execution-record--the-core-abstraction)
14. [Screen: Execution detail](#14-screen-execution-detail-executionsid)
15. [Performance analytics — the win/loss layer](#15-performance-analytics--the-winloss-layer)
16. [Agent decision trace](#16-agent-decision-trace-executionsid-tab-7--campaignsidgenn)
17. [Navigation model](#17-navigation-model)
18. [API additions](#18-api-additions)
19. [Data model additions](#19-data-model-additions)
20. [Backend requirements this imposes](#20-backend-requirements-this-imposes)
21. [Build phases](#21-build-phases)
22. [Cursor build prompt](#22-cursor-build-prompt)

**If you're looking for the "execution review" or "observability" spec** — sections 13–20 are it.
That content used to live in a separate `REVIEW_UI_SPEC.md`; it's merged in here now so there's one
document instead of two files that can drift out of sync with each other.

---

## 1. Purpose

Two distinct jobs, one application:

**Observe** — see what the automated agentic campaigns are doing: which generation is running, what
hypothesis it is testing, which parameters it chose and why, what the results were, how much budget
is left, and what it decided to try next.

**Control** — run your own experiments: pick a strategy, tune parameters by hand, launch a backtest,
compare it against previous runs and against what the agent found, and promote or kill candidates.

The manual mode is not a lesser sibling of the automated one. It shares the same execution path,
the same validation, the same trial registry, and the same guard rails. The only difference is who
chose the parameters.

---

## 2. The manual-tuning problem you must not create

This deserves its own section because it is the single easiest way to undermine everything the
validation subsystem was built for.

**Manual parameter tuning is multiple testing.** If you sit at a form, try 300 parameter
combinations by hand, and pick the one with the best Sharpe, you have run a 300-trial search — and
the resulting Sharpe needs exactly the same deflation as one the agent produced. The fact that a
human moved the sliders changes nothing statistically.

It is worse in one respect: automated sweeps log every trial by construction, while a human clicking
through configurations is tempted to remember only the winner.

**So the UI enforces:**

- Every manual run writes to the **same trial registry** as automated runs, tagged `source: manual`.
- Every result panel displays **your personal trial count** for that strategy alongside the Sharpe,
  and the DSR computed against it. Not buried in a tab — on the primary metrics block.
- A **session trial counter** is visible in the header while you are in the Strategy Lab. It goes up
  every time you run. It does not reset when you refresh.
- Attempting to promote a strategy whose DSR fails the gate shows the failure and requires an
  explicit override with a written reason, recorded in the audit log.
- The **holdout vault is locked in manual mode exactly as it is for agents.** Unlocking is a
  deliberate ceremony (see §5.9), not a checkbox.

If the UI makes hand-tuning feel consequence-free, it becomes the most dangerous component in the
system. Design it so the cost of each trial is always visible.

---

## 3. Stack decision & build timing

### Recommended stack

| Concern | Choice | Rationale |
|---|---|---|
| Framework | **Next.js 15 (App Router) + TypeScript** | Matches your existing Next.js/Vercel experience; server components reduce client bundle for data-heavy pages |
| Styling | **Tailwind + shadcn/ui** | Fast to build, consistent, no design-system overhead |
| Server state | **TanStack Query** | Caching, polling, invalidation for run/campaign data |
| Client state | **Zustand** | Lightweight; for lab form state and comparison selections |
| Charts — general | **Recharts** | Metrics bars, distributions, parameter surfaces |
| Charts — time series | **uPlot** | Equity curves with 100k+ points. Recharts will not handle this; see §10 |
| Tables | **TanStack Table** | Virtualized, sortable, filterable trial and trade tables |
| Forms | **react-hook-form + Zod** | Zod schemas generated from the backend pydantic parameter schemas |
| Real-time | **SSE** (Server-Sent Events) | Simpler than WebSocket for one-directional progress streams |
| Backend | **FastAPI** | Already in the plan; the UI is purely a client |

### When to build it

Building a rich UI against unstable APIs wastes effort. But you also want manual tuning available
early, when it is most useful for learning the data.

**Sequencing, using the canonical phase numbers from `SCOPE.md` §13:**

| Stage | UI | Reasoning |
|---|---|---|
| Phases 2–5 | **Streamlit**, deliberately throwaway, internal-only | You need to *see* the gold data, quality reports, backtests, and validation output immediately. Streamlit gets there in hours. It is not tested, not specified as a deliverable anywhere in this project, and you will delete it |
| End of Phase 5 | **Freeze the FastAPI contract** (§7) | Once the validation data model settles, the API stops churning |
| Phase 11 | **Build `fmtrader-web` in Next.js — the only specified UI deliverable** | By this point campaigns (7), risk-adjusted sizing (8), and possibly CME data (9) all exist, so there is a full system worth making observable, and the API contract has been stable since Phase 5 |

**This is the one and only UI plan in the project.** There is no second, competing "build it in
Next.js from Phase 6" plan — that earlier framing is superseded. Do not skip the Streamlit stage to
"do it properly the first time"; you will end up polishing an interface for a data model, and a
system, that are both about to change substantially across Phases 6–10.

---

## 4. Information architecture

```
/                          Dashboard — system state, active campaign, recent runs
/campaigns                 Campaign list
/campaigns/[id]            Campaign detail — generations, progress, budget, journal
/campaigns/[id]/gen/[n]    Generation detail — all configs tried, results table
/runs                      Run explorer — every backtest, filterable
/runs/[id]                 Run detail — equity, drawdown, trades, costs, metrics
/compare?runs=a,b,c        Side-by-side comparison
/lab                       Strategy Lab — manual parameter tuning ★
/lab/sweep                 Manual sweep builder
/strategies                Strategy registry — schemas, search spaces, status
/data                      Datasets, quality reports, coverage, candle viewer
/features                  Feature explorer — availability, distributions, correlations
/registry                  Trial registry explorer — parameter surfaces, DSR/PBO
/risk                      Risk console — limits, kill-switch, live positions (later)
/vault                     Holdout vault — locked status, unlock ceremony, audit log
/settings                  Budgets, LLM routing, cost models, workers
```

---

## 5. Screen specifications

### 5.1 Dashboard `/`

**Purpose:** answer "what is my system doing right now" in one glance.

- **System health strip** — QuestDB, Postgres, Temporal, MLflow, Ollama, worker pool. Green/amber/red with latency.
- **Resource meters** — memory used vs the 24 GB budget, broken down by Docker / Ollama / workers.
  This matters on your machine; make it prominent.
- **Active campaign card** — name, generation `n of m`, elapsed time, configs evaluated, best net
  Sharpe so far with its DSR, budget spent vs cap, and a live progress bar. Pause / Resume / Abort.
- **Recent runs** — last 10, with verdict badges (`NOISE` / `FRAGILE` / `CANDIDATE` / `VALIDATED`).
- **Alerts** — budget threshold crossed, quality gate failure, worker crash, kill-switch triggered.

### 5.2 Campaign detail `/campaigns/[id]`

The most important observability screen.

- **Header** — status pill (running / paused / complete / aborted), elapsed wall clock, controls.
- **Generation timeline** — horizontal stepper. Each generation shows configs evaluated, survivors,
  best net Sharpe, and spend. Click to drill into the generation.
- **Live activity feed** — SSE stream: which activity is executing, worker utilization, current config.
- **Budget panel** — spend against campaign / daily / per-generation caps, split by provider and by
  local vs frontier. A projection of when the cap will be hit at the current burn rate.
- **Research journal** — rendered Markdown, newest first, one entry per generation:
  hypothesis → parameters tried → metrics → survivors and why → next search space and why.
  This is the screen's centerpiece. Make it readable, not a log dump.
- **Search-space evolution** — visualize how parameter ranges narrowed or shifted across generations.
- **Cumulative results** — best-so-far net Sharpe over generations, with the DSR line beside it.
  When raw Sharpe climbs but DSR flattens, the campaign is finding search artifacts, not edge. That
  divergence should be visually obvious.

### 5.3 Generation detail `/campaigns/[id]/gen/[n]`

- **Hypothesis block** — the agent's stated hypothesis and its reasoning for this generation.
- **Configs table** — virtualized, every config with parameters as columns, sortable by any metric.
  Columns: net Sharpe (1.0×/1.5×), max DD, trades, cost drag, verdict. Filter and multi-select to compare.
- **Parameter surface** — 2D heatmap of any two parameters against a chosen metric. Look for plateaus,
  not spikes. Annotate the selected survivors on the surface.
- **Survivor rationale** — which candidates advanced to the fidelity lane and the critique text.
- **Fidelity results** — the NautilusTrader runs for survivors, with the vectorbt→Nautilus delta shown
  explicitly. A large gap means the fast lane is misleading you about fills.

### 5.4 Run detail `/runs/[id]`

- **Provenance header** — strategy, params, dataset id + content hash, git SHA, seed, lane, timestamp.
  Non-negotiable: a run without full provenance renders a warning banner.
- **Metrics block** — the mandatory report format from the `backtest-review` skill: gross vs net at
  1.0×/1.5×/2.0×, cost drag, trial count, DSR, PBO, regime breakdown, holdout status.
- **Equity curve** — uPlot, with drawdown shaded beneath and trade markers optional.
- **Drawdown chart** — underwater plot with the worst episodes annotated by duration.
- **Trade list** — virtualized table: entry/exit time and price, side, size, gross and net P&L,
  costs broken out, duration, MAE/MFE.
- **Return distribution** — histogram with the tail highlighted.
- **Cost breakdown** — spread vs commission vs slippage as a share of gross P&L.
- **Robustness panel** — top-5-trade removal result, session split, parameter neighborhood stability.
- **Actions** — compare, clone into the Lab, promote (gated), tag, archive.

### 5.5 Strategy Lab `/lab` ★ manual tuning

The screen you asked for. Layout: parameter panel left, results right, run history bottom.

**Parameter panel**
- Strategy selector, populated from the registry.
- **Form generated from the strategy's pydantic parameter schema** — no hand-written forms. Backend
  exposes JSON Schema; the frontend renders controls from it. Adding a strategy needs zero UI work.
- Controls typed by field: sliders with numeric entry for ranges, selects for choices, toggles for
  flags, conditional fields shown/hidden by dependency rules from the search-space DSL.
- **Live validity feedback** — a parameter combination that violates a constraint (fast EMA ≥ slow EMA)
  is flagged before you can run it.
- **Data requirement check** — if the strategy needs volume and the selected dataset lacks it, the
  run button is disabled with the reason stated. Do not let this fail at execution time.
- Dataset selector, date range, lane (vectorbt / Nautilus), cost multiplier, seed.
- **"Load config from"** — pull parameters from any previous run or from an agent's config to modify.

**Results panel**
- Runs inline and streams progress. Results render in the same format as `/runs/[id]`.
- **Delta view** — when you modify a parameter and re-run, show the diff against the previous run:
  which parameter changed, and how each metric moved. This is what makes iterative tuning legible.

**Run history (bottom rail)**
- Every run from this session, chronological, with the parameter delta and key metrics.
- **Session trial counter, always visible.** See §2.
- Multi-select to send to `/compare`.

**Sweep mode `/lab/sweep`**
- Define ranges rather than points, preview the config count before launching, and get a warning when
  the sweep size means the results will need heavy deflation.
- Launches through the same Temporal machinery as an agentic sweep, tagged `source: manual`.

### 5.6 Comparison `/compare`

- Overlaid equity curves, normalized.
- Metrics table with per-metric best highlighted — and a caution that picking the best from N compared
  runs is itself selection.
- Parameter diff matrix showing exactly what differs between runs.
- Rolling-correlation view: are these strategies actually different, or the same edge reparameterized?

### 5.7 Trial registry `/registry`

- Every configuration ever evaluated, across manual and automated sources.
- Filter by strategy, dataset, date, source, verdict.
- **Parameter surface explorer** — pick two parameters and a metric, get a heatmap over all trials.
- **DSR / PBO calculator** — select a subset, see the deflation given that subset's trial count.
- **Trial count by strategy** — the number that should make you uncomfortable before promoting anything.

### 5.8 Data explorer `/data`

- Dataset cards: symbol, timeframe, range, rows, content hash, capability flags
  (`has_volume`, `has_spread`, `has_open_interest`).
- **Quality report** — monthly coverage table, gap classification, flat-bar runs, outlier flags.
- **Candle viewer** — uPlot candlesticks with the flagged non-tradable regions shaded. Being able to
  see the no-tick weekend blocks in the gold data is worth more than any statistic about them.
- Ingestion history and snapshot manifests.

### 5.9 Holdout vault `/vault`

Deliberately austere. This screen exists to make a decision feel heavy.

- Per strategy: holdout status (`LOCKED` / `CONSUMED`), date range, and if consumed, when, by whom,
  and the result.
- **Unlock ceremony** — a modal that requires: selecting the exact strategy version, typing a written
  justification, confirming you understand this is single-use, and typing the strategy name to confirm.
- Immutable audit log of every unlock.
- No bulk actions. No convenience shortcuts. One at a time, by hand.

### 5.10 Risk console `/risk` *(Phase 7+)*

- Configured limits: per-trade, daily, drawdown, position, trade count, consecutive losses.
- Kill-switch — large, unambiguous, always reachable.
- Live positions and exposure once execution is connected.

### 5.11 Settings `/settings`

- Budget caps: per campaign, per generation, per day, per provider.
- LLM routing: local model selection, frontier model selection per node type, memory guard threshold.
- Cost model configuration per instrument and session.
- Worker pool size and memory ceilings.
- Data vendor credentials (write-only fields; never rendered back).

---

## 6. Real-time model

**SSE over WebSocket.** Progress is one-directional; control actions are ordinary POSTs. SSE is
simpler to operate, reconnects natively, and survives the laptop sleeping — which matters for
week-long campaigns.

```
GET /api/campaigns/{id}/stream        → generation.started, config.evaluated,
                                        generation.completed, budget.updated,
                                        journal.appended, campaign.paused, campaign.resumed
GET /api/runs/{id}/stream             → progress percentage, partial metrics
GET /api/system/stream                → health, memory, worker utilization
```

**Throttle aggressively.** A sweep evaluating 1,000 configs must not emit 1,000 events per second.
Batch `config.evaluated` into windows of 250 ms or every 25 configs, whichever comes first.

**Fall back to polling** via TanStack Query when the stream drops, so a dead SSE connection degrades
to a slower UI rather than a frozen one.

---

## 7. API contract

```
# Campaigns
GET    /api/campaigns                          list, filterable
POST   /api/campaigns                          create + launch
GET    /api/campaigns/{id}                     detail
POST   /api/campaigns/{id}/pause               → Temporal signal
POST   /api/campaigns/{id}/resume              → Temporal signal
POST   /api/campaigns/{id}/abort               → Temporal signal
PATCH  /api/campaigns/{id}/budget              → adjust_budget signal
GET    /api/campaigns/{id}/generations
GET    /api/campaigns/{id}/generations/{n}
GET    /api/campaigns/{id}/journal             Markdown entries
GET    /api/campaigns/{id}/stream              SSE

# Runs
GET    /api/runs                               filter: strategy, dataset, source, verdict, date
POST   /api/runs                               launch a manual run
GET    /api/runs/{id}
GET    /api/runs/{id}/equity                   downsampled series, ?points=2000
GET    /api/runs/{id}/trades                   paginated
GET    /api/runs/{id}/robustness               top-trade removal, session split, neighborhood
GET    /api/runs/{id}/stream                   SSE
POST   /api/runs/compare                       body: run_ids[]

# Strategies
GET    /api/strategies                         registry listing
GET    /api/strategies/{name}/schema           JSON Schema → drives the Lab form
GET    /api/strategies/{name}/search-space     ranges, choices, conditional dependencies
POST   /api/strategies/{name}/validate         param validity + data requirement check

# Sweeps
POST   /api/sweeps/preview                     body: ranges → returns config count + deflation warning
POST   /api/sweeps                             launch manual sweep

# Trial registry
GET    /api/registry/trials                    filterable, paginated
GET    /api/registry/surface                   ?x=param&y=param&metric= → heatmap data
POST   /api/registry/deflate                   body: trial_ids[] → DSR, PBO
GET    /api/registry/counts                    trial counts by strategy

# Data
GET    /api/datasets
GET    /api/datasets/{id}
GET    /api/datasets/{id}/quality
GET    /api/datasets/{id}/bars                 ?from=&to=&timeframe= downsampled
POST   /api/datasets/ingest

# Features
GET    /api/features                           registry + availability per dataset
GET    /api/features/{name}/distribution       ?dataset_id=

# Vault
GET    /api/vault/status                       per strategy
POST   /api/vault/unlock                       requires justification; irreversible
GET    /api/vault/audit

# System
GET    /api/system/health
GET    /api/system/resources                   memory breakdown, workers
GET    /api/system/stream                      SSE
GET    /api/settings  ·  PATCH /api/settings
```

---

## 8. Data model for the UI

```ts
type Verdict = 'NOISE' | 'FRAGILE' | 'CANDIDATE' | 'VALIDATED';
type RunSource = 'manual' | 'agent' | 'sweep';
type Lane = 'vectorbt' | 'nautilus';

interface Provenance {
  datasetId: string; contentHash: string;
  gitSha: string; seed: number; createdAt: string;
}

interface CostSensitivity { multiplier: number; netSharpe: number; netCagr: number; }

interface RunMetrics {
  gross: { sharpe: number; sortino: number; cagr: number; maxDd: number; maxDdDays: number };
  net:   { sharpe: number; sortino: number; cagr: number; maxDd: number; maxDdDays: number };
  costSensitivity: CostSensitivity[];      // 1.0x, 1.5x, 2.0x
  costDragPct: number;
  trades: number; hitRate: number; profitFactor: number; expectancy: number;
  turnover: number; exposurePct: number; tailRatio: number; ulcerIndex: number;
  trialCount: number; deflatedSharpe: number; pbo: number;
  regimes: Record<string, { sharpe: number; trades: number }>;
  holdoutConsumed: boolean;
}

interface Run {
  id: string; strategy: string; params: Record<string, unknown>;
  lane: Lane; source: RunSource; campaignId?: string; generation?: number;
  provenance: Provenance; metrics: RunMetrics; verdict: Verdict;
  status: 'queued' | 'running' | 'complete' | 'failed'; progress?: number;
}

interface BudgetState {
  campaign: { spentUsd: number; capUsd: number };
  daily:    { spentUsd: number; capUsd: number };
  byProvider: Record<string, number>;
  localCalls: number; frontierCalls: number;
  projectedExhaustionAt?: string;
}

interface Generation {
  n: number; hypothesis: string; searchSpace: Record<string, unknown>;
  configsEvaluated: number; survivors: string[];      // run ids
  bestNetSharpe: number; bestDsr: number;
  critique: string; nextSearchSpaceRationale: string;
  spendUsd: number; startedAt: string; completedAt?: string;
}

interface Campaign {
  id: string; name: string;
  status: 'running' | 'paused' | 'complete' | 'aborted' | 'failed';
  datasetId: string; generationsPlanned: number; generationsDone: number;
  budget: BudgetState; startedAt: string; elapsedSeconds: number;
  gates: { minDsr: number; maxPbo: number; costMultiplierTest: number };
}

interface DatasetCapabilities {
  hasVolume: boolean; hasSpread: boolean; hasOpenInterest: boolean; hasDepth: boolean;
}
```

---

## 9. Component inventory

**Primitives** — `MetricCard` · `VerdictBadge` · `StatusPill` · `ProvenanceHeader` ·
`BudgetMeter` · `ResourceMeter` · `TrialCounter` · `EmptyState` · `ErrorBoundary`

**Charts** — `EquityCurve` (uPlot) · `DrawdownChart` · `ReturnHistogram` · `ParameterSurface` (heatmap) ·
`CostBreakdown` · `RegimeBars` · `SharpeVsDsrChart` · `CandleChart` (uPlot, with shaded non-tradable regions)

**Data display** — `TrialsTable` (virtualized) · `TradesTable` (virtualized) · `MetricsBlock` ·
`RobustnessPanel` · `QualityReport` · `JournalEntry` (Markdown) · `ParamDiff`

**Forms & control** — `SchemaForm` (JSON Schema → controls) · `RangeBuilder` (sweep ranges) ·
`DatasetPicker` · `CampaignControls` · `UnlockCeremony` · `KillSwitch`

**Layout** — `AppShell` · `GenerationStepper` · `ComparisonGrid` · `SplitPane` (lab)

---

## 10. Performance requirements

| Concern | Constraint | Approach |
|---|---|---|
| Equity curves | 5 years of 1-minute bars ≈ 2M points. Recharts dies well before this | Server-side downsampling (LTTB) to ~2,000 points for display; uPlot for anything larger; full resolution only on zoom, fetched by range |
| Trial tables | Campaigns produce tens of thousands of rows | Server-side pagination + TanStack Virtual. Never fetch the full registry |
| SSE volume | A sweep can evaluate hundreds of configs per second | Batch and throttle server-side; the client should never receive more than ~4 updates/second |
| Candle viewer | 2M bars | Timeframe-aware: serve pre-aggregated 1h/1d for wide ranges, 1m only when zoomed in |
| Initial load | Dashboard interactive < 1.5 s | Server components for static shell, streaming for data panels |
| Memory | The browser competes with Docker, Ollama, and workers for 24 GB | Cap client-side cached datasets; release chart data on unmount; do not keep multiple full equity series in memory |

---

## 11. Guard rails enforced in the UI

| Guard rail | Implementation |
|---|---|
| Manual runs are counted as trials | Every Lab run POSTs to the same registry, tagged `source: manual` |
| Trial count always visible | Persistent counter in the Lab header; trial count shown beside every Sharpe |
| Sharpe never shown alone | `MetricsBlock` renders Sharpe, DSR, trial count, and cost drag as one unit — impossible to display in isolation |
| Data requirements checked pre-run | Run button disabled with an explicit reason when the dataset lacks a required capability |
| Cost realism visible | Net-at-1.5× shown adjacent to net-at-1.0× everywhere, not in a secondary tab |
| Holdout locked | No UI path reads holdout data outside the unlock ceremony |
| Promotion gated | Failing DSR blocks promotion; override requires written justification and is audit-logged |
| Sweep size warning | Preview shows config count and the deflation implication before launch |
| Provenance required | Runs lacking a complete provenance record render a warning banner |

---

## 12. Design language

Dense, instrument-panel aesthetic — this is a professional tool used for hours, not a marketing
surface. Priorities: information density over whitespace, legibility at a glance, and no decorative
motion.

- **Dark theme default** (you work in dark mode; the screenshots confirm it). Light theme optional.
- **Monospace for all numbers.** Tabular figures so columns align. This matters more than it sounds.
- **Color carries meaning, never decoration:** green/red strictly for P&L direction; amber strictly
  for caution states (budget nearing cap, DSR marginal, holdout consumed); neutral grays for everything
  else. Never encode meaning in color alone — pair with a label or icon.
- **Verdict badges** are the primary visual anchor in lists.
- **No animated transitions on data.** Charts update; they do not perform.
- Keyboard navigation throughout: `⌘K` command palette, `r` to re-run in the Lab, `c` to compare
  selection.

---

## 13. The Execution Record — the core abstraction

Everything in this spec depends on one idea: **every execution writes a complete, immutable record of
its own ingredients and steps.** If the record is incomplete, the execution is not reviewable, and an
unreviewable result is worthless regardless of its Sharpe ratio.

Build this in the backend first. The UI is a renderer for it.

### 13.1 Ingredients manifest

Everything that went into the execution, captured at run time — never reconstructed later.

```yaml
execution_id: exc_01J8K...
created_at: 2026-08-31T14:22:03Z
source: agent | manual | sweep
campaign_id: cmp_...            # null for manual
generation: 7                   # null for manual
parent_execution_id: exc_...    # what this was derived from, if anything

# --- CODE ---
code:
  git_sha: a3f9c21
  git_dirty: false
  fmtrader_version: 0.4.2
  lane: vectorbt | nautilus

# --- DATA ---
data:
  dataset_id: xauusd_1m_bid_2021-01-01_2026-08-31
  content_hash: sha256:7f3a...
  symbol: XAUUSD
  instrument_class: spot_cfd
  timeframe: 1m
  window: { start: 2021-01-01, end: 2025-08-31 }   # holdout excluded
  bars_total: 1_982_440
  bars_tradable: 1_744_112        # after flat-bar / no-tick exclusion
  bars_excluded: 238_328
  exclusion_reasons: { weekend: 201_440, holiday: 18_112, flat_run: 18_776 }
  capabilities: { has_volume: false, has_spread: false, has_open_interest: false }

# --- FEATURES ---
features:
  feature_set_version: fs_v12
  definition_hash: sha256:1b8e...
  members:
    - { name: volatility_atr_14, params: { period: 14 }, warmup_bars: 15 }
    - { name: momentum_rsi_2,    params: { period: 2 },  warmup_bars: 3 }
    - { name: trend_ema_9,       params: { period: 9 },  warmup_bars: 9 }
    - { name: regime_vol_quantile_60, params: { window: 60, buckets: 3 } }
  unavailable_requested: []       # features the strategy wanted but the dataset can't support

# --- LABELS (if ML in the loop) ---
labeling:
  method: triple_barrier
  pt_atr_multiple: 2.0
  sl_atr_multiple: 1.0
  time_barrier_bars: 30
  sample_weighting: uniqueness
  label_distribution: { up: 0.31, down: 0.29, timeout: 0.40 }

# --- STRATEGY ---
strategy:
  name: vwap_reversion_v2
  params: { ema_fast: 9, ema_slow: 21, rsi_period: 2, rsi_entry: 5, atr_stop_mult: 1.5 }
  param_schema_hash: sha256:9c2d...
  search_space_id: ss_gen7_narrow

# --- MODEL (if any) ---
model:
  type: lightgbm
  artifact_uri: mlflow://runs/8f2.../model
  hyperparams: { n_estimators: 400, max_depth: 5, learning_rate: 0.03 }
  calibration: isotonic
  conformal: { method: split, alpha: 0.10, coverage_observed: 0.906 }

# --- COSTS ---
costs:
  spread_source: assumed_constant     # measured | assumed_constant
  spread_value: 0.35
  spread_session_multipliers: { asia: 1.4, london: 1.0, ny: 1.0, off: 2.0 }
  commission_per_trade: 0.00
  slippage_model: vol_scaled
  slippage_base: 0.10
  multipliers_tested: [1.0, 1.5, 2.0]

# --- RISK ---
risk:
  sizing: fractional_kelly
  kelly_fraction: 0.25
  vol_target_annual: 0.15
  max_risk_per_trade_pct: 0.5
  conformal_gate: { enabled: true, max_interval_width: 0.35 }

# --- VALIDATION ---
validation:
  cv: { method: purged_kfold, folds: 6, embargo_bars: 60 }
  walkforward: { method: rolling, train_bars: 200_000, test_bars: 40_000, windows: 9 }
  holdout_used: false
  seed: 20260831

# --- ENVIRONMENT ---
environment:
  workers: 6
  python: 3.12.4
  key_deps: { vectorbt: 0.27.1, nautilus_trader: 1.208.0, polars: 1.17.0 }
```

### 13.2 Step trace

An ordered, timed record of every pipeline stage. Each entry captures inputs, outputs, duration, and
anything the stage decided.

```yaml
steps:
  - { seq: 1, stage: data_load,        status: ok, duration_ms: 4_120,
      out: { bars: 1_982_440, memory_peak_mb: 780 } }
  - { seq: 2, stage: data_filter,      status: ok, duration_ms: 890,
      out: { bars_kept: 1_744_112, excluded: 238_328 } }
  - { seq: 3, stage: feature_build,    status: ok, duration_ms: 31_400,
      out: { features: 4, nan_warmup_bars: 60, memory_peak_mb: 1_420 } }
  - { seq: 4, stage: label_generation, status: ok, duration_ms: 8_200,
      out: { labels: 1_744_052, distribution: {...} } }
  - { seq: 5, stage: signal_generation,status: ok, duration_ms: 2_100,
      out: { raw_signals: 4_812, after_regime_filter: 3_204,
             after_conformal_gate: 2_118, rejected_uncertainty: 1_086 } }
  - { seq: 6, stage: position_sizing,  status: ok, duration_ms: 340,
      out: { avg_size: 0.42, capped_by_max_risk: 118 } }
  - { seq: 7, stage: execution_sim,    status: ok, duration_ms: 6_900,
      out: { orders: 2_118, filled: 2_104, rejected: 14, partial: 0 } }
  - { seq: 8, stage: cost_application, status: ok, duration_ms: 210,
      out: { gross_pnl: 18_420.15, total_costs: 11_038.60, net_pnl: 7_381.55 } }
  - { seq: 9, stage: metrics,          status: ok, duration_ms: 1_100 }
  - { seq: 10, stage: validation,      status: ok, duration_ms: 44_300,
      out: { cv_folds: 6, wf_windows: 9, dsr: 0.41, pbo: 0.38 } }
  - { seq: 11, stage: verdict,         status: ok, duration_ms: 20,
      out: { verdict: CANDIDATE, gates_passed: 6, gates_failed: 1,
             failed: ["regime_consistency"] } }
```

**The funnel in step 5 is the most informative thing on the page.** Raw signals → after regime filter
→ after conformal gate → orders → fills. Seeing 4,812 signals collapse to 2,118 trades tells you
instantly whether your gates are doing something reasonable or strangling the strategy.

---

## 14. Screen: Execution detail `/executions/[id]`

The screen you will spend most of your time in. Tabbed, with a persistent header.

### Persistent header
Verdict badge · strategy name · source (agent gen 7 / manual) · net Sharpe with DSR and trial count ·
dataset + content hash (truncated, click to copy) · git SHA · run duration · lane.
Actions: compare · clone to Lab · promote (gated) · export record as JSON.

### Tab 1 — Overview
- **Metrics block** (mandatory format): gross vs net at 1.0×/1.5×/2.0×, cost drag %, trial count, DSR,
  PBO, regime breakdown, holdout status.
- **Equity curve** with drawdown shaded beneath.
- **Signal funnel** — the step-5 collapse rendered as a horizontal funnel with counts and drop reasons.
- **Verdict panel** — every gate with pass/fail, its threshold, and the actual value. A failed gate
  states plainly what would need to change.

### Tab 2 — Ingredients
The manifest from §13.1, rendered as collapsible sections rather than raw YAML. Each section shows what
was used and, where relevant, how it differs from the parent execution.

- **Data** — window, bar counts, exclusions with reasons, capability flags. A link to the dataset's
  quality report.
- **Features** — the table of features with their parameters and warmup. Flag any the strategy
  requested but the dataset could not supply.
- **Strategy params** — the values, with a **diff against the parent execution** highlighted. When
  reviewing an agent's generation, this is how you see what it actually changed.
- **Costs** — every assumption, prominently marked when `spread_source: assumed_constant`. On the
  current gold dataset that flag should be impossible to miss.
- **Risk, validation, model, environment** — same treatment.
- **Export** — download the full manifest as JSON. Two executions' manifests should diff cleanly in
  any text tool.

### Tab 3 — Steps
The step trace as a vertical timeline. Each step expands to show inputs, outputs, duration, memory
peak, and any warnings. Failed or skipped steps are visually distinct. A duration bar chart across
steps makes bottlenecks obvious.

### Tab 4 — Performance *(detailed in §15)*

### Tab 5 — Trades
Virtualized table: entry/exit time and price, side, size, gross P&L, costs broken out, net P&L,
duration in bars, MAE, MFE, exit reason (target / stop / time / signal). Filterable by outcome,
session, and regime. Click a row to jump the equity chart to that trade.

### Tab 6 — Validation
Per-fold CV results, per-window walk-forward results, regime segmentation, the DSR and PBO
computation with its trial-count input shown explicitly, and the robustness checks (top-5-trade
removal, session split, parameter neighborhood).

### Tab 7 — Agent trace *(agent-sourced executions only, detailed in §16)*

---

## 15. Performance analytics — the win/loss layer

A dedicated tab, because "did this work" has more dimensions than a Sharpe ratio.

### 15.1 Outcome summary
| Metric | Note |
|---|---|
| Total trades · wins · losses · scratches | |
| **Win rate** | Displayed adjacent to expectancy, never alone — see the caution below |
| Average win · average loss · win/loss ratio | |
| **Expectancy per trade** (gross and net) | The number that actually matters |
| Profit factor | Gross profit ÷ gross loss |
| Largest win · largest loss | |
| Payoff ratio | |

> **Caution rendered in the UI:** a high win rate is not evidence of a good strategy. A strategy
> winning 85% of trades while losing 6× on each loss is a losing strategy. The UI pairs win rate with
> expectancy in the same visual unit so the two are never read apart.

### 15.2 Streaks & sequencing
Longest win streak · longest loss streak · current streak distribution vs what a coin flip with the
same win rate would produce. Large deviation suggests serial dependence — which can be edge or can be
a regime artifact, and either way is worth knowing.

### 15.3 Distributions
- Trade P&L histogram, net, with the tails highlighted
- Trade duration histogram — for scalping, a long right tail often means stops aren't binding
- **MAE / MFE scatter** — maximum adverse vs maximum favorable excursion per trade. The single best
  diagnostic for whether stops and targets are placed sensibly. Winners clustering near the stop
  boundary means you are getting lucky, not right.
- R-multiple distribution

### 15.4 Breakdowns
Every one of these renders as a small-multiples grid of the same metric set:

- **By session** — Asia / London / NY / off-hours. Gold behaves very differently across these.
- **By hour of day** (UTC and exchange local)
- **By day of week**
- **By volatility regime** — using the quantile regime feature
- **By market regime period** — 2021 / 2022 / 2023–24 / 2025–26
- **By exit reason** — target vs stop vs time vs signal. A strategy where most profit comes from time
  exits is not doing what its author thinks it is.
- **By position size bucket** — does the sizing logic help or hurt?
- **Long vs short** — an edge that exists only on one side is a real finding, not a bug, but it
  changes deployment

### 15.5 Attribution
- **Cost attribution** — spread vs commission vs slippage as a share of gross P&L, and per trade
- **Top-trade dependence** — cumulative P&L with the top 1/5/10 trades removed, side by side
- **Time-to-profit** — how P&L accumulated; a curve that is flat for four years and vertical for two
  months is not a strategy

---

## 16. Agent decision trace `/executions/[id]` Tab 7 · and `/campaigns/[id]/gen/[n]`

When the automated Lab is driving, you need to see its reasoning, not just its output.

### Per generation
- **Hypothesis** — what the agent set out to test, in its own words
- **Search space** — the ranges it chose, diffed against the previous generation
- **Proposals** — every config proposed, with status: `accepted` · `rejected_schema` ·
  `rejected_duplicate` · `rejected_budget`. Rejections matter; a generation where 80% of proposals
  were duplicates means the agent is stuck
- **Evaluation results** — the configs table with metrics
- **Critique** — the model's assessment of the results
- **Selection rationale** — which survived, and the stated reasoning
- **Next search space rationale** — why it is moving where it is moving

### Per LLM call
A ledger table, expandable per row:
tier (local / frontier) · provider · model · node (hypothesize / critique / select) · tokens in/out ·
USD cost · latency · prompt (collapsed) · response (collapsed) · whether the output passed validation.

This is how you audit whether frontier spend is buying anything. If the critique node's expensive
calls consistently produce the same conclusions the local model reached, route it locally and save
the budget.

### Campaign-level
- **Sharpe vs DSR over generations** — plotted together. When raw Sharpe climbs while DSR flattens,
  the campaign is manufacturing search artifacts. This chart is the campaign's honesty meter.
- **Cumulative trial count** — the deflation denominator, growing in real time
- **Budget burn** — spend by tier and provider, with projected exhaustion
- **Convergence indicators** — proposal diversity, survivor overlap between generations, parameter
  range contraction. Three flat generations in a row means the campaign is done, whatever the budget says

---

## 17. Navigation model

Every screen drills down and back up cleanly:

```
Campaign  →  Generation  →  Execution  →  Trade
   ↑            ↑              ↑           ↑
   └── budget   └── proposals  └── steps   └── MAE/MFE, exit reason
   └── journal  └── critique   └── ingredients
   └── Sharpe/DSR              └── performance breakdowns
```

Lateral moves from any execution: **compare** (against siblings in the same generation, or against
any execution), **clone to Lab**, **view parent**, **view derived executions**.

The parent/child lineage matters. When the agent mutates a config across generations, you should be
able to walk the chain and see exactly which parameter change caused which metric movement.

---

## 18. API additions

Beyond the contract in §7 above:

```
GET  /api/executions                        filter: campaign, generation, strategy, verdict, source
GET  /api/executions/{id}                   summary + verdict + gates
GET  /api/executions/{id}/manifest          full ingredients record
GET  /api/executions/{id}/steps             step trace
GET  /api/executions/{id}/funnel            signal → order → fill counts with drop reasons
GET  /api/executions/{id}/performance       outcome summary, streaks, distributions
GET  /api/executions/{id}/breakdown         ?by=session|hour|dow|regime|exit_reason|side|size
GET  /api/executions/{id}/attribution       cost attribution, top-trade dependence, time-to-profit
GET  /api/executions/{id}/trades            paginated, filterable
GET  /api/executions/{id}/mae-mfe           scatter data
GET  /api/executions/{id}/lineage           parent chain + derived children
GET  /api/executions/{id}/agent-trace       LLM calls, proposals, critique  (agent-sourced only)
GET  /api/executions/{id}/export            full record as JSON
POST /api/executions/diff                   body: {a, b} → manifest + metric diff

GET  /api/campaigns/{id}/convergence        proposal diversity, survivor overlap, range contraction
GET  /api/campaigns/{id}/llm-ledger         all calls, filterable by node/provider/tier
GET  /api/campaigns/{id}/sharpe-vs-dsr      the honesty chart series
```

---

## 19. Data model additions

```ts
type StepStage =
  | 'data_load' | 'data_filter' | 'feature_build' | 'label_generation'
  | 'signal_generation' | 'position_sizing' | 'execution_sim'
  | 'cost_application' | 'metrics' | 'validation' | 'verdict';

interface Step {
  seq: number; stage: StepStage;
  status: 'ok' | 'warning' | 'failed' | 'skipped';
  durationMs: number; memoryPeakMb?: number;
  inputs?: Record<string, unknown>;
  outputs?: Record<string, unknown>;
  warnings?: string[];
}

interface SignalFunnel {
  rawSignals: number;
  afterRegimeFilter: number;
  afterConformalGate: number;
  afterRiskLimits: number;
  ordersSubmitted: number;
  ordersFilled: number;
  drops: { stage: string; count: number; reason: string }[];
}

interface OutcomeSummary {
  trades: number; wins: number; losses: number; scratches: number;
  winRate: number;
  avgWin: number; avgLoss: number; winLossRatio: number;
  expectancyGross: number; expectancyNet: number;   // always shown beside winRate
  profitFactor: number; payoffRatio: number;
  largestWin: number; largestLoss: number;
  longestWinStreak: number; longestLossStreak: number;
}

interface Breakdown {
  dimension: 'session'|'hour'|'dow'|'vol_regime'|'period'|'exit_reason'|'side'|'size_bucket';
  buckets: { key: string; trades: number; winRate: number;
             expectancyNet: number; netPnl: number; sharpe: number }[];
}

interface Gate {
  name: string; threshold: number | string; actual: number | string;
  passed: boolean; explanation: string;
}

interface AgentProposal {
  configHash: string; params: Record<string, unknown>;
  status: 'accepted' | 'rejected_schema' | 'rejected_duplicate' | 'rejected_budget';
  rejectionDetail?: string;
}

interface LlmCall {
  id: string; tier: 'local' | 'frontier'; provider: string; model: string;
  node: string; tokensIn: number; tokensOut: number; costUsd: number;
  latencyMs: number; prompt: string; response: string; outputValid: boolean;
}

interface ExecutionManifest {
  executionId: string; source: RunSource;
  campaignId?: string; generation?: number; parentExecutionId?: string;
  code: { gitSha: string; gitDirty: boolean; version: string; lane: Lane };
  data: { datasetId: string; contentHash: string; window: {start:string;end:string};
          barsTotal: number; barsTradable: number;
          exclusionReasons: Record<string, number>;
          capabilities: DatasetCapabilities };
  features: { setVersion: string; definitionHash: string;
              members: { name: string; params: Record<string,unknown>; warmupBars: number }[];
              unavailableRequested: string[] };
  labeling?: Record<string, unknown>;
  strategy: { name: string; params: Record<string,unknown>; paramSchemaHash: string };
  model?: Record<string, unknown>;
  costs: { spreadSource: 'measured'|'assumed_constant'; spreadValue: number;
           multipliersTested: number[]; [k: string]: unknown };
  risk: Record<string, unknown>;
  validation: { cv: Record<string,unknown>; walkforward: Record<string,unknown>;
                holdoutUsed: boolean; seed: number };
  environment: { workers: number; python: string; keyDeps: Record<string,string> };
}
```

---

## 20. Backend requirements this imposes

The UI can only render what the engine records. Add to the backend scope:

1. **`ExecutionRecorder`** — a context manager wrapping every execution that captures the manifest at
   start, appends step entries as stages complete, and writes the record atomically at the end. An
   execution that crashes still writes its partial record with the failure point marked.
2. **Manifest completeness check** — an execution whose manifest is missing a required section is
   marked `INCOMPLETE` and excluded from promotion and from comparison, with the reason surfaced.
3. **Funnel instrumentation** — signal generation, gating, sizing, and execution stages must emit
   counts and drop reasons, not just final trade lists.
4. **Per-trade enrichment** — MAE, MFE, exit reason, session, and regime label recorded at trade close.
   Computing these later from bars is possible but slow and error-prone; capture at source.
5. **LLM call ledger** — every call persisted with prompt and response. Storage cost is trivial next
   to the value of auditing agent reasoning after a week-long campaign.
6. **Lineage links** — `parent_execution_id` set whenever a config is derived from another.
7. **Immutability** — records are append-only. A re-run creates a new execution; it never edits an
   old one.

---

## 21. Build phases

This replaces two previously separate and conflicting build orders — an earlier "manual Lab first"
sequence and a later "observability first" revision that lived in a now-merged, separate document.
There is one order now: observability comes before manual tuning, because the agentic Lab (Phase 7)
is the primary driver and the manual Strategy Lab is a secondary tool for hand-probing what the agent
already found.

| Stage | Deliverable | Depends on / why here |
|---|---|---|
| **B0** | Streamlit throwaway: dataset viewer, quality report, single-run results. Internal only, not part of this app, deleted once B2+ ships | Phases 2–5 backend |
| **B1** | FastAPI contract frozen; TypeScript types generated from OpenAPI | End of Phase 5 |
| **B2** | Next.js shell: app router, layout, auth stub, health dashboard, settings | B1 |
| **B3** | **Execution Record** — ingredients manifest and step trace, backend + UI | Nothing past this point is reviewable without it. Backend half (`ExecutionRecorder`) is actually built in Phase 4, not here — see §20 |
| **B4** | Execution detail screen — inputs, steps, results, trades, all mandatory metrics | B3 |
| **B5** | Performance analytics — win/loss, streaks, MAE/MFE, session and regime breakdowns | B4 |
| **B6** | Campaign & generation observability — timeline, SSE live feed, journal rendering, budget panel | Phase 7 backend |
| **B7** | Agent decision trace — prompts, model, cost, reasoning, accepted/rejected proposals | Phase 7 backend |
| **B8** | Comparison & registry — cross-execution analysis, parameter surfaces, DSR/PBO calculator | B4–B5 |
| **B9** | Data & feature explorer — candle viewer, feature explorer | B4 |
| **B10** | **Manual Strategy Lab** — schema-driven form, manual runs, delta view, session trial counter | B4, B8. Deliberately built after the observability stack, not before it — see §1 |
| **B11** | Vault ceremony, risk console, kill-switch | Phase 8 backend |

**Why the Lab moved from early to late:** an earlier version of this plan built the Lab at B3–B4
priority, on the reasoning that manual runs are worthless without a results view worth reading. That
is still true — B4 is still a Lab prerequisite — but it undersold how much more of the system depends
on the Execution Record and campaign observability existing first. If you are relying on the agent to
drive most experimentation, you will spend far more time in B4–B8 than in B10, so build in that order.

---

## 22. Cursor build prompt

> Paste this when starting frontend work. Read `docs/FRONTEND_SPEC.md` alongside it.

```
Build `fmtrader-web`, the control and observability UI for the fmengine platform.

Read docs/SCOPE.md and docs/FRONTEND_SPEC.md first. The spec is authoritative — where this
prompt and the spec disagree, follow the spec and tell me about the conflict.

Stack: Next.js 15 App Router + TypeScript + Tailwind + shadcn/ui + TanStack Query + TanStack
Table + Zustand + react-hook-form/Zod + Recharts (general) + uPlot (time series) + SSE.

Non-negotiable behaviors:
1. The MetricsBlock component renders Sharpe, Deflated Sharpe, trial count, and cost drag as a
   single indivisible unit. There must be no code path that displays a Sharpe ratio alone.
2. Every manual run in the Strategy Lab POSTs to the trial registry tagged source=manual, and
   the session trial counter in the Lab header increments and persists across refreshes.
3. Strategy parameter forms are generated at runtime from JSON Schema fetched from
   /api/strategies/{name}/schema. Do not hand-write a form for any strategy.
4. Before enabling the run button, validate the selected strategy's data requirements against
   the selected dataset's capability flags. If unmet, disable it and state exactly which
   capability is missing and why.
5. No UI path reads holdout data except through the unlock ceremony modal in /vault.
6. Equity curves use uPlot with server-downsampled data. Never render more than ~2,000 points
   without user-initiated zoom.
7. SSE events are throttled client-side as a backstop; assume the server batches but never
   trust it to.

Build order: F2 shell → F3 run explorer + detail → F4 Strategy Lab → F5 campaign observability
→ F6 registry → F7 data → F8 vault/risk.

Generate TypeScript types from the FastAPI OpenAPI schema; do not hand-maintain the interfaces
in §8 of the spec — treat them as the target shape, not the source of truth.

Stop after each stage, show me what runs, and report what you assumed.
```

---