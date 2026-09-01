# fmengine / fmtrader — Development Plan

FinnMetrics quantitative research and execution engine.
Target: production-grade, multi-asset, agent-assisted strategy discovery with a credible path to live capital.

> **This file no longer maintains its own phase list, risk register, or toolkit-placement table.**
> Earlier versions did, in parallel with `SCOPE.md` and `BUILD_PLAN.md`, and the three drifted out of
> sync — the exact problem a repo review surfaced. `SCOPE.md` §13 is now the single canonical roadmap
> and phase numbering for the whole project; `BUILD_PLAN.md` is the detailed phase-by-phase execution
> guide with tests. This file keeps only the narrative context — the reasoning behind the stack and
> tooling choices — that doesn't duplicate either of those.

---

## Guiding position

The hard part of this project is not building the engine. It is building an engine that does not lie
to you. A 1-minute gold series over 5.5 years is ~2 million bars; an agentic loop running for a week
across parallel workers can evaluate tens of thousands of configurations against it. Under those
conditions a high in-sample Sharpe is not evidence of anything — random signals produce them routinely.

So the plan front-loads the machinery that separates signal from search artifact: purged validation,
a trial registry, deflated Sharpe, PBO, a locked holdout, and honest cost modeling. **The agentic
pipeline (`SCOPE.md` §13, Phase 7) is built after that machinery (Phase 5), not before.** An agent
turned loose on an unvalidated backtest harness is a very efficient generator of expensive false
confidence.

The provider framework for pluggable news/sentiment/fundamentals (Phase 6) is likewise built before
the agentic pipeline, not after, so the agent's search space is designed with those feature sources
in mind from its first campaign rather than requiring a redesign once they arrive. See
`PROVIDER_ARCHITECTURE.md` for the full design.

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
| UI | Next.js + FastAPI, Phase 11 | The only specified UI deliverable — see `FRONTEND_SPEC.md` §3. A disposable, untested internal Streamlit script may exist for Phases 2–5 only |

**On vectorbt:** the open-source version is sufficient for triage. Defer any decision about the Pro
version until the fast lane is a measured bottleneck.

**On NautilusTrader over LEAN:** its actor/message-passing model is close to the Proto.Actor patterns
you already ran in production on the EC Trading Platform, and the same strategy code path runs in
backtest, paper, and live — no reimplementation tax at the exact moment reimplementation is most
dangerous.

---

## On your teammate's toolkit

The list is legitimate — these are real, well-established methods. But they differ sharply in when
they become useful, and two of them cannot be used on the current dataset at all. Placement and
phase numbers for each: `SCOPE.md` §8, "Statistical methods — assessment and placement".

The short version: fractional Kelly and the conformal filter are both good ideas, gated on
probability calibration existing first (Phase 5–8) and both landing in the risk module (Phase 8).
Quantile volatility regime is cheap and usable immediately (Phase 3). The Bayesian classifier is a
fine baseline that gradient-boosted trees will likely beat. Hawkes process and Random Matrix Theory
are both correctly identified as currently inapplicable — Hawkes needs tick data that doesn't exist
until CME futures onboarding (Phase 9), and RMT needs a multi-asset universe that doesn't exist yet
at all.

Your teammate's closing caveat is the most important sentence in their message and it's correct: none
of these produce signals on their own. The practical priority order they suggest — volatility-based
stops, fixed-fractional risk, fractional Kelly, probability-based filtering — is sound, and it's
roughly what the risk module (Phase 8) implements.

**The one thing missing from their list** is multiple-testing correction. Given that you plan to run
an agent generating thousands of configurations for a week, that omission matters more than any
method on the list. Deflated Sharpe Ratio and PBO (Phase 5) are what make the rest of it trustworthy.

---

## What "done" looks like through the validation core

A system where you can define a strategy once, sweep it across thousands of parameterizations, have
those results automatically corrected for search effort, have an agent propose and refine the next
generation within a hard budget, pause the whole thing for a day and resume it, and read a journal
that explains every decision — with a holdout you haven't touched still waiting to give you one
honest answer at the end.

That is a research platform worth trusting. Live capital is a separate decision that comes after it.

See `SCOPE.md` §13 for the full eleven-phase roadmap and exit criteria, and `BUILD_PLAN.md` for the
phase-by-phase implementation and test plan.
