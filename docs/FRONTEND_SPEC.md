# fmtrader — Frontend Specification

**Component:** `fmtrader-web` — control and observability UI for the `fmengine` platform
**Status:** Living document
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
13. [Build phases](#13-build-phases)
14. [Cursor build prompt](#14-cursor-build-prompt)

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

**Recommended sequencing:**

| Stage | UI | Reasoning |
|---|---|---|
| Phases 2–4 | **Streamlit**, deliberately throwaway | You need to *see* the gold data, quality reports, and first backtests immediately. Streamlit gets there in hours. Accept that you will delete it |
| Phase 5 | **Define and freeze the FastAPI contract** | Once the validation data model settles, the API stops churning |
| Phase 6+ | **Build `fmtrader-web` in Next.js** | Campaigns exist, results are structured, the contract is stable |

Do not skip the Streamlit stage to "do it properly the first time" — you will end up building a
polished interface for a data model you are about to change.

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

## 13. Build phases

| Stage | Deliverable | Depends on |
|---|---|---|
| **F0** | Streamlit throwaway: dataset viewer, quality report, single-run results | Phase 2–4 backend |
| **F1** | FastAPI contract frozen; TypeScript types generated from OpenAPI | Phase 5 |
| **F2** | Next.js shell: app router, layout, auth stub, health dashboard, settings | F1 |
| **F3** | Run explorer + run detail with all charts and the mandatory metrics block | F2 |
| **F4** | **Strategy Lab** — schema-driven form, manual runs, delta view, session trial counter | F3 |
| **F5** | Campaign observability — timeline, SSE feed, budget panel, journal rendering | Phase 6 backend |
| **F6** | Trial registry explorer, parameter surfaces, DSR/PBO calculator, comparison view | F4 |
| **F7** | Data explorer, candle viewer, feature explorer | F3 |
| **F8** | Vault ceremony, risk console, kill-switch | Phase 7 backend |

F4 is the one you specifically asked for; F3 is its prerequisite because manual runs are worthless
without a results view worth reading.

---

## 14. Cursor build prompt

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

*Maintenance: update this spec when the API contract changes. The frontend must never become the
place where a validation guard rail is quietly bypassed for convenience.*