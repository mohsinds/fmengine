# fmengine / fmtrader — Development Plan

FinnMetrics quantitative research and execution engine.
Target: production-grade, multi-asset, agent-assisted strategy discovery with a credible path to live capital.

---

## Guiding position

The hard part of this project is not building the engine. It is building an engine that does not lie
to you. A 1-minute gold series over 5.5 years is ~2 million bars; an agentic loop running for a week
across parallel workers can evaluate tens of thousands of configurations against it. Under those
conditions a high in-sample Sharpe is not evidence of anything — random signals produce them routinely.

So the plan front-loads the machinery that separates signal from search artifact: purged validation,
a trial registry, deflated Sharpe, PBO, a locked holdout, and honest cost modeling. **The agentic
pipeline is built after that machinery, not before.** An agent turned loose on an unvalidated backtest
harness is a very efficient generator of expensive false confidence.

---

## Stack decisions

| Concern | Choice | Why |
|---|---|---|
| Language / deps | Python 3.12 + `uv` | Lockfile reproducibility, fast resolution |
| Bulk data | Polars + Parquet | Memory-efficient on 24 GB, fast on arm64 |
| Time-series store | QuestDB | High ingest throughput, SQL, light footprint |
| Metadata / registry | Postgres | Trial registry, journal, cost ledger, Temporal + MLflow backing |
| Fast backtest lane | vectorbt | Thousands of configs in minutes for triage |
| Fidelity lane | NautilusTrader | Event-driven, realistic fills, backtest→paper→live parity |
| Orchestration | Temporal | Durable week-long runs, pause/resume, survives restarts |
| Experiment tracking | MLflow | Run comparison, artifacts, model registry |
| Agent framework | LangGraph | Stateful graph loop, fits the generation cycle |
| Local LLM | Ollama (Metal) | Free bulk inference; native macOS for GPU access |
| Frontier LLM | Claude / OpenAI / Gemini | Gating decisions only, hard budget caps |
| UI | Streamlit → FastAPI-backed | Fast now, replaceable later without backend rewrite |

**On vectorbt:** the open-source version is sufficient for triage. Defer any decision about the Pro
version until the fast lane is a measured bottleneck.

**On NautilusTrader over LEAN:** its actor/message-passing model is close to the Proto.Actor patterns
you already ran in production on the EC Trading Platform, and the same strategy code path runs in
backtest, paper, and live — no reimplementation tax at the exact moment reimplementation is most
dangerous.

---

## Phases

### Phase 1 — Foundation (week 1)
uv workspace, repo skeleton, Docker stack (QuestDB, Postgres, Temporal, Redis, MLflow) with memory
caps, Ollama models pulled, Makefile, ruff/mypy/pytest/pre-commit green, `.cursor/` config in place.

**Done when:** `make up && make check` is green and the Temporal UI, QuestDB console, and MLflow UI all load.

### Phase 2 — Data layer (week 1–2)
Canonical bar contract. Dukascopy adapter. Quality gate. Snapshot manifests with content hashing.
QuestDB mirror. Session calendar. Futures continuous-contract interface (pass-through for XAUUSD).

**Done when:** the gold CSV is ingested, the quality report prints a month-by-month coverage table,
row counts reconcile between Parquet and QuestDB, and 10 hand-checked bars match the raw file.

**Watch for:** epoch-ms timestamps, bid-only data, no volume column, flat-bar no-tick regions.

### Phase 3 — Features & labeling (week 2–3)
Indicator library with capability declarations and gating. Triple-barrier labeling with ATR-scaled
barriers. Meta-labeling. Sample weights for label overlap. Versioned feature store driven by YAML.

**Done when:** full feature build on 2M bars completes inside the memory budget, all indicator tests
including property tests pass, and requesting a volume feature on this dataset raises a clear error.

### Phase 4 — Two-lane backtesting (week 3–4)
vectorbt sweep runner (chunked, 6 workers). NautilusTrader fidelity runner. Cost models with spread,
commission, slippage, and session-dependent widening. Full metrics suite. Cost-sensitivity sweeps.

**Done when:** buy-and-hold produces matching net returns in both lanes within tolerance, and a
deliberately look-ahead-biased test strategy is caught.

### Phase 5 — Validation & anti-overfitting (week 4–5) ← **the critical phase**
Purged/embargoed CV. Walk-forward (rolling + anchored). Regime segmentation. Trial registry.
Deflated Sharpe Ratio. PBO via CSCV. Locked holdout vault with token-gated access and irreversible
unlock logging. Leakage test suite with planted bugs.

**Done when:** every planted leakage bug is caught, and the holdout guard test proves the vault is
unreadable through normal code paths.

### Phase 6 — Agentic research pipeline (week 5–7)
Temporal `ResearchCampaignWorkflow` with pause/resume/abort signals and per-generation checkpoints.
LangGraph nodes: hypothesize → validate → fast sweep → shortlist → fidelity → critique → select →
journal. LLM router (local bulk / frontier gating). Budget governor with hard caps and a cost ledger.
Research journal rendered as Markdown.

**Done when:** a 24-hour trial campaign runs, is paused mid-generation, the machine is restarted, the
campaign resumes correctly, and the journal explains every decision it made.

### Phase 7 — Risk & sizing (week 7–8)
Fractional Kelly (default 0.25), volatility targeting, probability calibration, split-conformal
uncertainty gate, and the limits/kill-switch service sitting between signal and execution.

### Phase 8 — CME futures onboarding (week 8–10)
Databento adapter for GC/MGC. Real volume and open interest. Continuous-contract construction with
volume-crossover rolls. Re-validate the surviving strategies on real futures data — expect results to
change, sometimes substantially. Volume and microstructure features unlock here.

### Phase 9 — Execution & paper trading (week 10–12)
`BrokerAdapter` interface, IBKR adapter via NautilusTrader, paper trading on the identical code path,
reconciliation, idempotent order IDs, independent kill-switch.

### Phase 10 — Observability & UI (parallel, ongoing)
Streamlit dashboard over FastAPI: campaign state, generation results, equity curves, parameter
surfaces, journal. Structured logs with correlation IDs.

### Later — optional modules
Sentiment/news (publication-time-correct alignment), equities with point-in-time fundamentals, crypto
via CCXT, RMT/Ledoit-Wolf portfolio construction once multi-asset.

---

## On your teammate's toolkit

The list is legitimate — these are real, well-established methods. But they differ sharply in when
they become useful, and two of them cannot be used on the current dataset at all.

| Method | Verdict | When |
|---|---|---|
| **Fractional Kelly sizing** | Use it, with calibrated probabilities | Phase 7. Uncalibrated inputs make Kelly actively dangerous — calibration is the prerequisite, not an optional refinement |
| **Quantile volatility regime** | Use it now, cheap and genuinely useful | Phase 3 |
| **Conformal filter** | Use it — this is the sharpest idea in the list | Phase 7. Directly implements "high probability but high uncertainty → skip or shrink" |
| **Bayesian classifier** | Fine as a baseline, but gradient-boosted trees will likely beat it | Phase 3–5. The valuable part isn't Bayes specifically, it's calibrated probabilities |
| **Hawkes process** | Blocked — needs trade/tick arrival data | Phase 8+, after CME tick data. Cannot run on volume-less 1m bars |
| **Random Matrix Theory** | Blocked — needs a multi-asset universe | Later. Meaningless while trading one instrument |

Your teammate's closing caveat is the most important sentence in their message and it's correct: none
of these produce signals on their own. The practical priority order they suggest — volatility-based
stops, fixed-fractional risk, fractional Kelly, probability-based filtering — is sound, and it's
roughly what Phase 7 implements.

**The one thing missing from their list** is multiple-testing correction. Given that you plan to run
an agent generating thousands of configurations for a week, that omission matters more than any
method on the list. Deflated Sharpe Ratio and PBO are what make the rest of it trustworthy.

---

## Risk register

| Risk | Severity | Mitigation |
|---|---|---|
| Agent finds thousands of spurious edges | **Critical** | Trial registry + DSR + PBO + locked holdout, built in Phase 5 before any agent runs |
| Bid-only, volume-less data misleads cost and volume assumptions | High | Capability gating that raises loudly; download ask side; conservative assumed spread; re-validate on CME data |
| Scalping edge inside the spread | High | Net-of-cost reporting always; 1.5×/2.0× cost sensitivity as a hard gate |
| 24 GB memory contention (Docker + Ollama + workers) | Medium | Explicit budgets, capped containers, memory check before model load, configurable worker count |
| LLM API overspend on a week-long campaign | Medium | Pre-call cost estimation, hard caps at three levels, ledger, graceful degradation to local |
| Campaign lost to a restart or machine sleep | Medium | Temporal durable execution with per-generation checkpoints |
| XAUUSD results don't transfer to GC futures | Medium | Treat Phase 1–7 results as *pipeline validation*, not tradable conclusions; re-validate in Phase 8 |
| Scope sprawl across asset classes | Medium | Adapters at the edges; one instrument working end-to-end before adding a second |

---

## What "done" looks like for Phase 1–7

A system where you can define a strategy once, sweep it across thousands of parameterizations, have
those results automatically corrected for search effort, have an agent propose and refine the next
generation within a hard budget, pause the whole thing for a day and resume it, and read a journal
that explains every decision — with a holdout you haven't touched still waiting to give you one
honest answer at the end.

That is a research platform worth trusting. Live capital is a separate decision that comes after it.
