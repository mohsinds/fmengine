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
| QuestDB (pg wire) | `postgresql://admin:quest@localhost:8812/qdb` |
| Postgres | `postgresql://fmtrader:fmtrader@localhost:5432/fmtrader` |
| Temporal UI | http://localhost:8233 |
| MLflow | http://localhost:5001 |
| Ollama | http://localhost:11434 |

Change the default credentials in `.env` before this touches anything real.

## How to verify each phase

| Phase | Verification |
|---|---|
| 1 Foundation | `docker compose ps` all healthy · `make check` green · `ollama run qwen2.5-coder:7b "say ok"` responds |
| 2 Data | Ingest completes · quality report prints monthly coverage · Parquet and QuestDB row counts match · 10 bars hand-checked against the raw CSV |
| 3 Features | Indicator tests + property tests pass · full feature build stays inside memory budget · requesting a volume feature raises a clear error |
| 4 Backtest | Buy-and-hold nets identical in both lanes within tolerance · planted look-ahead strategy is caught · cost drag reported |
| 5 Validation | Every planted leakage bug caught · holdout guard test proves the vault is unreadable via normal paths · DSR/PBO computed from the trial registry |
| 6 Agentic | 24h trial campaign runs · pause mid-generation · restart the machine · resume correctly · journal explains each decision |
| 7 Risk | Kelly sizing tests · conformal gate rejects high-uncertainty signals · kill-switch halts on breach |

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
- Spot CFD ≠ CME GC futures → treat Phase 1–7 results as pipeline validation, not tradable conclusions
