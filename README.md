# fmengine setup bundle

Drop these into the root of your `fmengine` repo.

```
fmengine/
├── SETUP_PROMPT.md          # paste into Cursor Composer, work phase by phase
├── PLAN.md                  # roadmap, stack rationale, risk register
├── docker-compose.yml       # QuestDB + Postgres + Temporal + Redis + MLflow (memory-capped)
└── .cursor/
    ├── mcp.json
    ├── rules/               # 00 context (always) · 10 python · 20 quant (always) · 30 data · 40 agentic
    ├── commands/            # /phase-start /leak-audit /new-strategy /campaign /onboard-data
    ├── agents/              # quant-researcher · infra-engineer · red-team
    └── skills/              # indicator-implementation · backtest-review · data-onboarding
```

## Install order

```bash
# 1. toolchain
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. infra (Docker already installed)
mkdir -p scripts data/{raw,catalog,nautilus,snapshots} artifacts
# add scripts/init-multiple-dbs.sh (Cursor generates it in Phase 1)
docker compose up -d
docker compose ps          # all healthy?

# 3. local models — native macOS, NOT Docker (needs Metal GPU)
brew install ollama
ollama serve &
ollama pull qwen2.5-coder:7b
ollama pull qwen2.5:14b-instruct-q4_K_M
ollama pull nomic-embed-text

# 4. hand SETUP_PROMPT.md to Cursor and start Phase 1
```

## Service endpoints

| Service | URL |
|---|---|
| QuestDB console | http://localhost:9000 |
| QuestDB (pg wire) | `postgresql://$QUESTDB_USER:$QUESTDB_PASSWORD@localhost:8812/qdb` |
| Postgres | `postgresql://$POSTGRES_USER:$POSTGRES_PASSWORD@localhost:5432/fmtrader` |
| Temporal UI | http://localhost:8233 |
| MLflow | http://localhost:5001 |
| Ollama | http://localhost:11434 |

**Before running `make up` for the first time:** copy `.env.example` to `.env` and set real
`QUESTDB_PASSWORD` / `POSTGRES_PASSWORD` values — `openssl rand -base64 24` works well. This is not
optional cleanup for later: `docker-compose.yml` uses `${VAR:?error}` syntax for these, so the stack
will refuse to start at all with a named error if `.env` is missing or a credential is blank. There
is no working default to fall back on, by design.

## How to verify each phase

Canonical phase numbers per `SCOPE.md` §13 — if this table ever disagrees with that one, `SCOPE.md`
wins.

| Phase | Verification |
|---|---|
| 1 Foundation | `docker compose ps` all healthy · `make check` green · `ollama run qwen2.5-coder:7b "say ok"` responds |
| 2 Data | Ingest completes · quality report prints monthly coverage · Parquet and QuestDB row counts match · 10 bars hand-checked against the raw CSV |
| 3 Features | Indicator tests + property tests pass · full feature build stays inside memory budget · requesting a volume feature raises a clear error |
| 4 Backtest + Execution Recorder | Buy-and-hold nets identical in both lanes within tolerance · planted look-ahead strategy is caught · cost drag reported · every run writes a complete manifest |
| 5 Validation ★ | Every planted leakage bug caught · noise-calibration sweep returns `NOISE` · holdout guard test proves the vault is unreadable via normal paths · DSR/PBO computed from the trial registry |
| 6 Provider framework | Core pipeline runs unchanged with zero providers registered · a planted `event_time` join is caught · the `SyntheticNewsProvider` produces deterministic features |
| 7 Agentic | 24h trial campaign runs · pause mid-generation · restart the machine · resume correctly · journal explains each decision |
| 8 Risk | Kelly sizing tests · conformal gate rejects high-uncertainty signals · kill-switch halts on breach |
| 9 CME futures | GC/MGC ingested with open interest · continuous series validated against known roll dates · a previously-validated strategy is re-run on futures data |
| 10 Execution | Paper trades execute on the identical code path as backtest · reconciliation survives a forced disconnect |
| 11 Observability & UI | Any execution can be opened and its ingredients reconstructed without guessing · win rate never renders without expectancy beside it |

## Two things to do on the data before Phase 3

1. **Download the ask side.** Re-run `dukascopy-node` for the ask series so you can derive a real
   spread. Bid-only means every cost number until then is an assumption. Also check whether your
   version of the tool exposes a volumes flag — if it does, pull volumes too.
2. **Switch to Parquet output** for future pulls (`-f parquet`). CSV is fine for this one file, but
   Parquet is the right default for multi-year 1-minute data.

## Known gaps in the current dataset — encode these, don't work around them

- No volume → VWAP, OBV, MFI, volume profile, cumulative delta, and Hawkes intensity are **unavailable**
- Bid only → spread is unmeasured; cost models use a conservative config constant, never zero
- Flat-bar runs mark no-tick periods → flag as non-tradable, never let a strategy transact there
- Spot CFD ≠ CME GC futures → treat Phase 1–8 results as pipeline validation, not tradable conclusions. Re-validate in Phase 9
