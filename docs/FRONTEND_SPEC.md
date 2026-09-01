# fmtrader — Execution Review & Observability Spec

**Supersedes the build ordering in `FRONTEND_SPEC.md` §13.** The rest of that document still applies —
stack, design language, performance constraints, guard rails. This document defines what the UI must
show when the automated Lab is the primary driver and your role is review rather than tuning.

**Last revised:** 2026-08-31

---

## 1. Revised priority

You are relying on the agentic Lab to drive experimentation. That makes **observability the product**,
not a supporting feature. The UI's job is to let you reconstruct, after the fact, exactly what
happened in any execution — what went in, what each step did, what came out, and why the system moved
on to whatever it tried next.

The manual Strategy Lab drops from priority 1 to priority 4. It stays in scope, because you will want
to hand-probe something the agent found interesting, but it is no longer what the UI is *for*.

### Revised build order

| Stage | Deliverable | Why here |
|---|---|---|
| **R1** | **Execution Record** — the ingredients manifest and step trace. Backend + UI | Nothing else is reviewable without it |
| **R2** | Execution detail screen — inputs, steps, results, trades | The screen you will live in |
| **R3** | Performance analytics — win/loss, streaks, MAE/MFE, session and regime breakdowns | The "did it actually work" layer |
| **R4** | Campaign & generation observability — timeline, live feed, journal, budget | The layer above individual executions |
| **R5** | Agent decision trace — prompts, model, cost, reasoning, accepted/rejected proposals | Why the system chose what it chose |
| **R6** | Comparison & registry — cross-execution analysis, parameter surfaces, DSR/PBO | Making sense of thousands of executions |
| **R7** | Data & feature explorer | Diagnosing when results look strange |
| **R8** | Manual Strategy Lab | Hand-probing, once you know what to probe |

---

## 2. The Execution Record — the core abstraction

Everything in this spec depends on one idea: **every execution writes a complete, immutable record of
its own ingredients and steps.** If the record is incomplete, the execution is not reviewable, and an
unreviewable result is worthless regardless of its Sharpe ratio.

Build this in the backend first. The UI is a renderer for it.

### 2.1 Ingredients manifest

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

### 2.2 Step trace

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

## 3. Screen: Execution detail `/executions/[id]`

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
The manifest from §2.1, rendered as collapsible sections rather than raw YAML. Each section shows what
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

### Tab 4 — Performance *(detailed in §4)*

### Tab 5 — Trades
Virtualized table: entry/exit time and price, side, size, gross P&L, costs broken out, net P&L,
duration in bars, MAE, MFE, exit reason (target / stop / time / signal). Filterable by outcome,
session, and regime. Click a row to jump the equity chart to that trade.

### Tab 6 — Validation
Per-fold CV results, per-window walk-forward results, regime segmentation, the DSR and PBO
computation with its trial-count input shown explicitly, and the robustness checks (top-5-trade
removal, session split, parameter neighborhood).

### Tab 7 — Agent trace *(agent-sourced executions only, detailed in §5)*

---

## 4. Performance analytics — the win/loss layer

A dedicated tab, because "did this work" has more dimensions than a Sharpe ratio.

### 4.1 Outcome summary
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

### 4.2 Streaks & sequencing
Longest win streak · longest loss streak · current streak distribution vs what a coin flip with the
same win rate would produce. Large deviation suggests serial dependence — which can be edge or can be
a regime artifact, and either way is worth knowing.

### 4.3 Distributions
- Trade P&L histogram, net, with the tails highlighted
- Trade duration histogram — for scalping, a long right tail often means stops aren't binding
- **MAE / MFE scatter** — maximum adverse vs maximum favorable excursion per trade. The single best
  diagnostic for whether stops and targets are placed sensibly. Winners clustering near the stop
  boundary means you are getting lucky, not right.
- R-multiple distribution

### 4.4 Breakdowns
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

### 4.5 Attribution
- **Cost attribution** — spread vs commission vs slippage as a share of gross P&L, and per trade
- **Top-trade dependence** — cumulative P&L with the top 1/5/10 trades removed, side by side
- **Time-to-profit** — how P&L accumulated; a curve that is flat for four years and vertical for two
  months is not a strategy

---

## 5. Agent decision trace `/executions/[id]` Tab 7 · and `/campaigns/[id]/gen/[n]`

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

## 6. Navigation model

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

## 7. API additions

Beyond the contract in `FRONTEND_SPEC.md` §7:

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

## 8. Data model additions

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

## 9. Backend requirements this imposes

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

## 10. What this changes in the roadmap

| Document | Change |
|---|---|
| `SCOPE.md` §6.15 | `api` & `ui` module scope expands: the Execution Record is a first-class backend concern, not a UI detail |
| `SCOPE.md` §13 | Phase 4 (Backtest) gains the `ExecutionRecorder` and funnel instrumentation as exit criteria |
| `FRONTEND_SPEC.md` §13 | Build order replaced by §1 of this document |
| `PLAN.md` | Phase 10 (Observability) moves earlier and grows; parts of it become prerequisites for trusting Phase 6 output |

**Practical consequence:** build the `ExecutionRecorder` during Phase 4, not Phase 10. Retrofitting
provenance capture onto an engine that has already run a week-long campaign means that campaign's
results are unreviewable. Instrument first, then run.

---

*The test for this UI: six weeks after a campaign finishes, can you open any single execution and
reconstruct — without guessing — what data it saw, what features it built, what parameters it used,
what costs it assumed, how its signals were filtered, how its trades performed across sessions and
regimes, and why the agent chose to try it? If yes, the platform is reviewable. If no, its results
are anecdotes.*