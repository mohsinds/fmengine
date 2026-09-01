# Cursor Setup Prompt — `fmengine` / `fmtrader` (FinnMetrics)

> Paste this whole file into Cursor Composer (Agent mode, max context). Work through it phase by phase.
> Stop after each phase, run the stated verification, and report before continuing.

---

## 0. Context you must internalize before writing any code

I am building **`fmengine`** — a production-grade quantitative research and execution engine. The Python solution inside it is **`fmtrader`** (FinnMetrics, https://finnmetrics.com).

**Scope now:** Gold (XAUUSD 1-minute bars from Dukascopy, free) → later CME GC/MGC futures via Databento.
**Scope later:** Crypto, US equities (with fundamentals), FX. The architecture must not assume gold, must not assume futures, and must not assume any single broker.

**Machine:** MacBook Pro, Apple M5 Pro, 15 CPU cores (5 efficiency + 10 performance), 16-core GPU, 24 GB unified LPDDR5, 1 TB SSD (~994 GB data volume), macOS Tahoe 26.5.2, Docker installed.

**Hard memory constraint:** 24 GB unified memory is shared between macOS, Docker containers, local LLM inference, and parallel backtest workers. Every design decision must respect a budget of roughly:
- Docker stack (QuestDB + Postgres + Temporal + Redis + MLflow): ≤ 6 GB
- Local LLM (Ollama): ≤ 8 GB resident
- Backtest worker pool: ≤ 6 GB total (6 workers × ~1 GB)
- macOS + Cursor + headroom: ≥ 4 GB

Do not design anything that assumes unbounded RAM. Memory-map Parquet, stream where possible, and make worker counts configurable with conservative defaults.

**Non-negotiable engineering principles:**
1. **Same data contract everywhere.** One canonical bar schema flows through ingestion → features → backtest → live. Adding CME futures or equities means adding an *adapter*, never editing core code.
2. **Two-lane backtesting.** `vectorbt` = fast triage lane (thousands of configs). `NautilusTrader` = fidelity lane (realistic fills, costs, event-driven). Nothing is ever declared "working" on the vectorbt lane alone.
3. **Deterministic live path.** No LLM call ever sits between a market data tick and an order. LLMs live in the offline research tier only.
4. **Every experiment is reproducible.** Data snapshot hash + config hash + code git SHA + seed are recorded for every run, or the run is invalid.
5. **Overfitting is the primary enemy.** An agentic loop running for a week will generate thousands of configs and *will* find spurious edges by chance. Multiple-testing correction is a first-class subsystem, not an afterthought. See Phase 6.

---

## 1. Repository layout

Create this structure. Use `uv` for dependency management (fast, lockfile-based) and Python 3.12.

```
fmengine/
├── pyproject.toml                 # uv workspace root
├── uv.lock
├── .python-version                # 3.12 
├── docker-compose.yml
├── .env.example
├── Makefile
├── README.md
├── download/                      # raw vendor drops (gitignored)
│   └── xauusd-m1-bid-2021-01-01-2026-08-31.csv
├── data/                          # gitignored
│   ├── raw/                       # immutable vendor copies
│   ├── catalog/                   # canonical Parquet (partitioned)
│   ├── nautilus/                  # NautilusTrader ParquetDataCatalog
│   └── snapshots/                 # dataset manifests (hash + metadata)
├── artifacts/                     # gitignored: run outputs, models, reports
├── src/fmtrader/
│   ├── __init__.py
│   ├── config/                    # pydantic-settings, typed config trees
│   ├── core/                      # domain models, enums, contracts, errors
│   ├── data/
│   │   ├── adapters/              # dukascopy.py, databento.py, ccxt.py, ibkr.py
│   │   ├── ingest.py              # adapter → canonical Parquet
│   │   ├── quality.py             # gap/outlier/monotonicity validation
│   │   ├── catalog.py             # read/write canonical catalog + snapshots
│   │   ├── resample.py            # m1 → m5/m15/H1, session-aware
│   │   └── contracts.py           # futures roll / continuous series builder
│   ├── features/
│   │   ├── indicators/            # trend.py, momentum.py, volatility.py, volume.py, microstructure.py
│   │   ├── regime.py              # quantile vol regime, HMM (later)
│   │   ├── labeling.py            # triple-barrier, meta-labeling
│   │   ├── pipeline.py            # feature set assembly + versioning
│   │   └── store.py               # versioned feature Parquet store
│   ├── strategy/
│   │   ├── base.py                # Strategy ABC — engine-agnostic
│   │   ├── registry.py            # name → class, with param schema
│   │   ├── space.py               # search-space DSL (ranges, choices, conditionals)
│   │   └── library/               # ema_cross.py, vwap_reversion.py, donchian_break.py, ml_gate.py
│   ├── backtest/
│   │   ├── vbt/                   # fast lane runner
│   │   ├── nautilus/              # fidelity lane runner + venue config
│   │   ├── costs.py               # spread, commission, slippage models
│   │   ├── metrics.py             # Sharpe, Sortino, Calmar, DD, PSR, DSR
│   │   └── validation/            # purged_kfold.py, walkforward.py, cscv_pbo.py
│   ├── models/
│   │   ├── train.py               # GBM baseline (LightGBM/XGBoost)
│   │   ├── calibrate.py           # Platt / isotonic probability calibration
│   │   ├── conformal.py           # split-conformal uncertainty gate
│   │   └── bayes.py               # Bayesian classifier baseline
│   ├── risk/
│   │   ├── sizing.py              # fractional Kelly, vol targeting, fixed-fractional
│   │   ├── limits.py              # per-trade, daily, drawdown kill-switch
│   │   └── portfolio.py           # RMT / correlation cleaning (multi-asset, later)
│   ├── agents/
│   │   ├── graph.py               # LangGraph research loop
│   │   ├── nodes/                 # hypothesize, design, evaluate, critique, select
│   │   ├── llm.py                 # router: local (Ollama) vs frontier APIs
│   │   ├── budget.py              # token/cost governor with hard caps
│   │   └── journal.py             # human-readable rationale log per iteration
│   ├── orchestration/
│   │   ├── workflows/             # Temporal workflows (research loop, ingestion)
│   │   ├── activities/            # Temporal activities (backtest, train, llm call)
│   │   └── worker.py
│   ├── sentiment/                 # OPTIONAL plug-in module (news, sentiment)
│   │   ├── sources/               # rss.py, newsapi.py, (later) filings.py
│   │   └── features.py            # sentiment → aligned time-series features
│   ├── execution/
│   │   ├── brokers/               # ibkr.py, (later) tradovate.py, ccxt.py
│   │   └── paper.py
│   ├── api/                       # FastAPI: runs, experiments, journal, control
│   └── ui/                        # Streamlit dashboard (Phase 5)
├── tests/
│   ├── unit/
│   ├── property/                  # hypothesis-based invariants
│   └── integration/
├── notebooks/                     # research scratch, never imported by src
└── .cursor/                       # provided separately
```

---

## 2. Phase 1 — Foundation & infrastructure

### 2.1 Toolchain
```bash
# Install uv if absent
curl -LsSf https://astral.sh/uv/install.sh | sh
uv init --python 3.12
```

### 2.2 Core dependencies
Add via `uv add`. Group them in `pyproject.toml` optional-dependency groups so a lean runtime install is possible.

**core:** `polars`, `pandas`, `numpy`, `pyarrow`, `pydantic>=2`, `pydantic-settings`, `structlog`, `typer`, `rich`, `duckdb`
**data:** `questdb` (ingress client), `httpx`, `tenacity`
**backtest:** `vectorbt`, `nautilus_trader`, `numba`, `scipy`, `statsmodels`
**ml:** `scikit-learn`, `lightgbm`, `xgboost`, `mapie` (conformal), `optuna`
**agents:** `langgraph`, `langchain-core`, `langchain-anthropic`, `langchain-openai`, `langchain-google-genai`, `ollama`, `langsmith`
**orchestration:** `temporalio`, `redis`
**tracking:** `mlflow`, `psycopg[binary]`, `sqlalchemy`, `alembic`
**api/ui:** `fastapi`, `uvicorn`, `streamlit`, `plotly`
**dev:** `pytest`, `pytest-cov`, `hypothesis`, `ruff`, `mypy`, `pre-commit`, `ipykernel`

> **Apple Silicon note:** verify `vectorbt` and `nautilus_trader` wheels install cleanly on arm64/Python 3.12. If `vectorbt` fights the Numba version, pin Numba to the version its release notes specify and record the pin with a comment explaining why. If `nautilus_trader` needs a Rust toolchain, install via `rustup`.

### 2.3 Docker stack — `docker-compose.yml`
Provision these services with explicit memory limits (see the provided `docker-compose.yml`):

| Service | Purpose | Mem cap |
|---|---|---|
| `questdb` | tick/bar time-series store, fast ingest + SQL | 2 GB |
| `postgres` | experiment metadata, agent journal, Temporal + MLflow backing | 1 GB |
| `temporal` + `temporal-ui` | durable, pausable, resumable research workflows | 1.5 GB |
| `redis` | cache, rate limiting, worker coordination | 512 MB |
| `mlflow` | experiment tracking, run comparison, model registry | 1 GB |

Ollama runs **natively on macOS** (not in Docker) so it gets Metal GPU acceleration.

### 2.4 Local models via Ollama
```bash
brew install ollama && ollama serve
ollama pull qwen2.5-coder:7b     # code/config generation for the agent loop
ollama pull qwen2.5:14b-instruct-q4_K_M   # reasoning workhorse, ~9GB — use alone
ollama pull nomic-embed-text     # embeddings for the research journal / RAG
```
Given 24 GB shared memory, **only one 14B model may be resident at a time**, and not while a large parallel backtest sweep is running. Encode this as a hard constraint in the LLM router: local model tier must query available memory before loading and fall back to the 7B model under pressure.

**Verification for Phase 1:** `make up` brings the stack healthy; `make check` runs ruff + mypy + pytest green on an empty suite; `ollama run qwen2.5-coder:7b "say ok"` responds.

---

## 3. Phase 2 — Data layer

### 3.1 The input file
`download/xauusd-m1-bid-2021-01-01-2026-08-31.csv`

```
timestamp,open,high,low,close
1609632000000,1909.718,1909.718,1909.718,1909.718
1609632060000,1909.718,1909.718,1909.718,1909.718
```

Facts you must handle explicitly:
- `timestamp` is **epoch milliseconds, UTC**. Convert to timezone-aware UTC datetimes. Never store naive datetimes anywhere in this system.
- **There is no `volume` column, and this is bid-side only.** Consequences to encode in code and docs:
  - All volume-dependent indicators (VWAP, OBV, volume profile, cumulative delta, Hawkes on trade arrivals) are **unavailable** for this dataset. The feature pipeline must *fail loudly with a clear message* when a strategy requests a volume feature on a dataset whose manifest declares `has_volume: false`. Silent NaN propagation is forbidden.
  - Spread cannot be measured from this file. Re-run `dukascopy-node` with the **ask** side (`-p ask`, and check whether your version exposes a volumes flag) and produce `xauusd-m1-ask-*.csv`. Build a derived `spread` series from bid/ask mid. Until then, cost models must use a **conservative assumed spread constant** declared in config, not zero.
  - Long flat runs (identical OHLC values, as in the sample rows above) indicate illiquid/no-tick periods — weekends, holidays, rollover gaps. Detect and flag these; do not let a strategy "trade" in them.

### 3.2 Canonical bar schema (the contract)
```python
# src/fmtrader/core/contracts.py
class Bar(BaseModel):
    ts: datetime          # tz-aware UTC, bar OPEN time (document this choice)
    symbol: str           # "XAUUSD", "GCZ26", "AAPL", "BTC-USD"
    instrument_class: Literal["spot_cfd","futures_raw","futures_continuous","equity","crypto"]
    timeframe: str        # "1m","5m","1h","1d"
    open: float; high: float; low: float; close: float
    volume: float | None = None
    open_interest: float | None = None    # futures only
    bid: float | None = None
    ask: float | None = None
```
Store as Parquet partitioned by `symbol/timeframe/year=YYYY/month=MM`. Use Polars for all bulk transforms.

### 3.3 Ingestion CLI
```bash
fmtrader data ingest \
  --adapter dukascopy \
  --path download/xauusd-m1-bid-2021-01-01-2026-08-31.csv \
  --symbol XAUUSD --timeframe 1m --instrument-class spot_cfd --side bid
```
Pipeline: read → validate → normalize to `Bar` schema → write canonical Parquet → write snapshot manifest → optionally mirror into QuestDB.

### 3.4 Data quality gate (`quality.py`) — must run on every ingest
Emit a report, and **hard-fail** on structural problems:
- timestamps strictly monotonic, no duplicates
- gaps vs expected session calendar (classify: weekend / holiday / rollover / anomalous)
- OHLC invariants: `low <= min(open,close)`, `high >= max(open,close)`, all > 0
- outliers: bar return beyond N median-absolute-deviations flagged for review
- flat-bar runs (zero-range bars repeating) counted and reported
- coverage % per month, printed as a table

### 3.5 Snapshot manifests
Every ingest writes `data/snapshots/<dataset_id>.json`:
```json
{
  "dataset_id": "xauusd_1m_bid_2021-01-01_2026-08-31",
  "content_hash": "sha256:...",
  "source": "dukascopy-node", "side": "bid",
  "rows": 0, "start": "...", "end": "...",
  "has_volume": false, "has_spread": false,
  "quality_report": {...},
  "created_at": "..."
}
```
Every backtest result must reference a `dataset_id` + `content_hash`. A run without one is rejected.

### 3.6 Futures-readiness (build the seam now, implement fully at CME phase)
Implement `contracts.py` with the interface for continuous-series construction (back-adjusted / Panama, ratio-adjusted, unadjusted) and roll rules (volume crossover, open-interest crossover, fixed days-before-expiry). For XAUUSD it is a pass-through no-op. This guarantees swapping to GC later is an adapter + config change, not a rewrite.

**Verification for Phase 2:** ingest completes; quality report printed; `SELECT count(*) FROM ohlcv` in QuestDB matches Parquet row count; round-trip test `write → read → assert frame equality` passes.

---

## 4. Phase 3 — Features, indicators, labeling

### 4.1 Indicator library
Implement as **pure, vectorized Polars/NumPy functions** with a thin registry. Each declares its data requirements (`requires_volume`, `min_lookback`) so the pipeline can validate before running.

- **Trend:** SMA, EMA, WMA, HMA, DEMA/TEMA, ADX/DMI, Aroon, Supertrend, linear-regression slope, Ichimoku
- **Momentum:** RSI (incl. short-period RSI(2)/RSI(7) for scalping), Stochastic, CCI, Williams %R, ROC, MACD + histogram slope, TSI
- **Volatility:** ATR & normalized ATR, Bollinger Bands + %B + bandwidth/squeeze, Keltner, Donchian, Chaikin volatility, Parkinson / Garman-Klass / Yang-Zhang realized vol estimators, rolling realized vol, **quantile volatility regime** (rank current vol within trailing distribution → discrete regime label)
- **Volume (gated off for this dataset):** VWAP + bands, anchored VWAP, OBV, MFI, volume profile / POC, cumulative delta
- **Microstructure (CME phase):** order-book imbalance, trade-arrival intensity, **Hawkes-process clustering intensity**, spread dynamics
- **Session/time:** minute-of-day, session bucket (Asia/London/NY), time-since-session-open, day-of-week, macro-release proximity flag
- **Cross-asset (later):** gold/silver ratio, gold/copper ratio, DXY, real yields

> Prefer implementing core indicators yourself over adding TA-Lib (C dependency friction on arm64). Cross-validate a handful against a reference implementation in tests to prove correctness.

### 4.2 Labeling
- **Triple-barrier method**: profit-take barrier, stop-loss barrier, time barrier — barriers scaled by ATR, not fixed pips.
- **Meta-labeling**: primary rule generates side; a secondary ML model predicts whether to *take* that trade. This is usually where ML adds the most value in practice.
- Emit `sample_weight` based on label uniqueness/overlap so overlapping outcomes don't inflate effective sample size.

### 4.3 Feature store
Versioned Parquet keyed by `(dataset_id, feature_set_version, symbol, timeframe)`. A feature set is defined declaratively in YAML so the agent layer can propose new sets as data, not code.

**Verification for Phase 3:** indicator unit tests pass including edge cases (NaN warmup, insufficient lookback, constant series); property tests assert e.g. `bb_lower <= sma <= bb_upper`; a full feature build on the gold dataset completes within memory budget and is reported with timing.

---

## 5. Phase 4 — Two-lane backtesting + honest cost modeling

### 5.1 Lane A — vectorbt (triage)
Parameter sweeps across thousands of configs. Chunk sweeps to respect memory; never materialize the full cartesian product in RAM at once. Parallelize with a configurable process pool (**default 6 workers** on this machine).

### 5.2 Lane B — NautilusTrader (fidelity)
Same `Strategy` definition, adapted. Bar-by-bar event-driven, explicit order types, realistic fills. Configure a venue matching the eventual live target (initially a synthetic CFD venue; later COMEX for GC/MGC).

### 5.3 Cost model — the make-or-break piece for scalping
Config-driven, per-instrument, per-session:
- **spread**: measured from bid/ask when available, else a conservative constant; widen during off-session hours
- **commission**: per-contract or per-notional
- **slippage**: base + volatility-scaled component; different for market vs limit orders
- **funding/rollover** for CFDs, **roll cost** for futures

Report gross **and** net-of-cost metrics side by side, always. Add a `cost_sensitivity` sweep: re-run the best configs at 1.5× and 2× assumed costs. **If the edge dies at 1.5× costs, it is not an edge** — mark the strategy `fragile` in the results store.

### 5.4 Metrics
Sharpe, Sortino, Calmar, CAGR, max drawdown + duration, hit rate, profit factor, average win/loss, expectancy per trade, turnover, exposure, trade count, **cost drag as % of gross P&L**, tail ratio, Ulcer index.

**Verification for Phase 4:** a trivially known strategy (e.g. buy-and-hold) produces identical net returns in both lanes within tolerance; a deliberately look-ahead-biased strategy is caught by the leakage test in Phase 6.

---

## 6. Phase 5 — Validation & anti-overfitting subsystem (build BEFORE the agent loop)

This is the most important phase in the project. Build it before any agent is allowed to run.

- **Purged, embargoed K-fold CV** — remove training samples whose label windows overlap test folds; embargo a buffer after each test fold.
- **Walk-forward analysis** — rolling and anchored; report per-window metrics, not just the aggregate.
- **Regime segmentation** — report metrics separately for 2021 (post-COVID drift), 2022 (rate-hike volatility), 2023–2024, 2025–2026. A strategy that only works in one regime must be labeled as such.
- **Trial registry** — a Postgres table logging *every* configuration ever evaluated, with its metrics. This is the denominator for multiple-testing correction.
- **Deflated Sharpe Ratio (DSR)** and **Probability of Backtest Overfitting (PBO)** via CSCV — computed using the trial count from the registry. Any strategy the agent proposes must clear a DSR threshold, not just a raw Sharpe threshold.
- **Locked holdout vault** — reserve the most recent ~12 months. Agents and sweeps **must not be able to read it**. Enforce in code: the catalog reader raises unless a `HoldoutUnlockToken` is passed, and unlocking is logged as an irreversible event per strategy. A strategy gets *one* holdout evaluation, ever. Record it.
- **Leakage tests** — a test suite that plants known look-ahead bugs (shifted labels, future-peeking indicators) and asserts the validator catches them.

---

## 7. Phase 6 — Agentic research pipeline (Temporal + LangGraph)

### 7.1 Why Temporal
The loop must run for a week or longer, survive machine sleep/restarts, and support **pause/resume**. Temporal gives durable execution, automatic retries, signal-based pause/resume, and a UI showing exactly where the workflow is. Use `signal` handlers for `pause`, `resume`, `adjust_budget`, `abort`.

### 7.2 Workflow shape
```
ResearchCampaignWorkflow(campaign_config)
  └── loop over generations (until budget/time/convergence):
        1. HypothesizeActivity     → LLM proposes N candidate strategy configs
                                     (from journal history + prior results)
        2. ValidateProposalActivity→ schema/sanity check, dedupe vs trial registry
        3. FastSweepActivity       → vectorbt lane, parallel, chunked
        4. ShortlistActivity       → filter by net metrics + DSR gate
        5. FidelityActivity        → NautilusTrader lane on shortlist
        6. CritiqueActivity        → LLM reviews results, writes rationale
        7. SelectActivity          → choose survivors + next-generation search space
        8. JournalActivity         → persist inputs, results, rationale, decision
        9. CheckpointActivity      → durable state; safe pause point
```

### 7.3 LLM routing & budget governor (`agents/llm.py`, `agents/budget.py`)
Tiered by cost:
- **Tier L (local, free):** Ollama — bulk hypothesis generation, config mutation, summarization. Handles the high-volume work.
- **Tier F (frontier, paid):** Claude / OpenAI / Gemini — only for *gating decisions*: critiquing a shortlist, proposing a genuinely novel direction, final generation review, writing the human-readable report.

The governor enforces:
- hard USD cap per campaign, per generation, and per day
- per-provider caps and a kill-switch on breach
- cost estimation *before* a call, with refusal if it would breach
- full token/cost ledger in Postgres
- graceful degradation: on budget exhaustion, fall back to Tier L and continue rather than crashing the campaign

### 7.4 The agent must never
- see or query the holdout vault
- write to the trial registry directly (only activities do, after validation)
- generate arbitrary executable Python that gets `exec`'d — it proposes **structured configs against a declared search space schema**, which are validated and instantiated by trusted code. This matters for both safety and reproducibility.

### 7.5 The research journal
Every generation writes a human-readable entry: hypothesis, exact params tried, metrics, why survivors were chosen, what the next search space is and why. This is what I will read to understand the campaign. Render it in the dashboard and export as Markdown.

---

## 8. Phase 7 — Risk & sizing (`risk/`)

- **Fractional Kelly** position sizing with a configurable fraction (default 0.25 — full Kelly is too aggressive for real deployment) and a hard cap on per-trade risk.
- **Volatility targeting** — scale position size inversely to realized volatility to keep risk contribution stable across regimes.
- **Conformal prediction gate** — split-conformal intervals around model outputs; if the prediction set is too wide (uncertainty too high), **skip the trade regardless of predicted direction**. This directly implements the "60% bullish but high uncertainty → skip or size down" rule.
- **Probability calibration** — Platt/isotonic on the classifier before any Kelly math. Uncalibrated probabilities make Kelly sizing actively dangerous.
- **Limits & kill-switches** — max per-trade loss, max daily loss, max drawdown halt, max position, max trades/day, consecutive-loss circuit breaker. These live in a service *between* signal and execution, never inside strategy code.
- **Portfolio layer (deferred to multi-asset):** Random Matrix Theory / Ledoit-Wolf shrinkage for cleaning correlation matrices. Genuinely useful for equity baskets; irrelevant while trading one instrument. Build the seam, defer the implementation.

---

## 9. Phase 8 — Optional plug-in modules (design now, implement later)

Both must be **strictly optional** — the core engine runs fully without them.

- **Sentiment/news:** `sentiment/sources/` adapters produce timestamped, point-in-time-correct records. Critical rule: a news item is only usable at features time `t` if it was *published* before `t` — no revision leakage. Feature builder aligns to bars with an explicit publication-lag parameter.
- **Fundamentals (equities phase):** point-in-time fundamentals with as-reported vs restated distinction. Using restated figures is a classic, subtle look-ahead bias.

Register both as optional feature providers behind the same interface the technical indicators use.

---

## 10. Phase 9 — Execution & brokers

- Abstract `BrokerAdapter` interface: connect, subscribe, submit/modify/cancel, positions, account, reconcile.
- Implement via NautilusTrader's adapters where available. **IBKR first** (paper then live), given the existing IBKR Pro account.
- Idempotent order submission with client-generated order IDs; reconciliation on reconnect; a mandatory kill-switch reachable independently of the strategy process.
- Paper trading must use the *same* strategy code path as backtest and live. Any divergence is a bug.

---

## 11. Phase 10 — Observability & UI

- **structlog** JSON logging with run/campaign correlation IDs.
- **MLflow** for run tracking, params, metrics, artifacts (equity curves, trade lists), model registry.
- **Temporal UI** for campaign state, pause/resume control.
- **Streamlit dashboard** (`fmtrader ui`): campaign overview, generation-by-generation results table, equity curves, parameter-importance view, and the research journal rendered inline.
- **FastAPI** endpoints so the UI is a client, not a monolith — a Next.js frontend can replace Streamlit later without backend changes.

---

## 12. Makefile targets to provide

```
make up / down / logs        # docker stack
make install                 # uv sync
make check                   # ruff + mypy + pytest
make ingest                  # ingest the gold CSV
make features                # build default feature set
make sweep                   # vectorbt triage sweep
make backtest                # nautilus fidelity run
make worker                  # start Temporal worker
make campaign                # launch a research campaign
make pause / resume          # signal a running campaign
make ui                      # streamlit dashboard
```

---

## 13. Execution order — do not skip ahead

1. Phase 1 (toolchain + Docker + Ollama) → verify → report
2. Phase 2 (data layer + quality gate + snapshots) → verify → report
3. Phase 3 (indicators + labeling + feature store) → verify → report
4. Phase 4 (two lanes + cost models + metrics) → verify → report
5. Phase 5 (validation & anti-overfitting) → verify → report
6. Phase 6 (Temporal + LangGraph campaign) → verify → report
7. Phase 7 (risk & sizing) → verify → report
8. Phases 8–10 as scoped later

At each phase: write tests first where practical, keep functions pure and typed, document every non-obvious decision in a short ADR under `docs/adr/`.

**When something is ambiguous, ask me rather than guessing.** When you make an assumption anyway, state it explicitly in your report.
