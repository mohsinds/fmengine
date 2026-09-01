# Running fmengine

Operator guide for the local research stack (Docker + API + Next.js Lab).

## Current status checklist

| Component | Port | How to check | Notes |
|---|---|---|---|
| Next.js UI | 3000 | http://localhost:3000 | `make ui` |
| FastAPI | 8000 | http://127.0.0.1:8000/api/system/health | `make api` |
| QuestDB | 9000 | http://localhost:9000 | console |
| MLflow | 5001 | http://localhost:5001 | |
| Temporal UI | 8233 | http://localhost:8233 | gRPC 7233 |
| Postgres | 5432 | `nc -z 127.0.0.1 5432` | |
| Redis | 6379 | `nc -z 127.0.0.1 6379` | |
| Ollama | 11434 | http://127.0.0.1:11434/api/tags | native Metal, not Docker |

## One-time setup

```bash
# PATH for uv (Apple Silicon / user install)
export PATH="$HOME/.local/bin:$PATH"

cd /path/to/fmengine

# Credentials (required — compose will not start without them)
cp .env.example .env
# set QUESTDB_USER/PASSWORD and POSTGRES_USER/PASSWORD (openssl rand -base64 24)

# Python (keep api + orchestration + tracking together — a single --extra drops others)
uv sync --extra api --extra orchestration --extra tracking --group dev

# Frontend
cd web && npm install && cd ..

# Docker stack
make up
docker compose ps   # all should be Up / healthy

# Models (optional for agentic campaigns)
ollama serve &
ollama pull qwen2.5-coder:7b
```

## Long-running research campaign (Temporal)

Temporal and MLflow stay empty until you start a **worker** and a campaign with `--temporal`.

```bash
export PATH="$HOME/.local/bin:$PATH"
export MLFLOW_TRACKING_URI=http://127.0.0.1:5001
cd /path/to/fmengine

# Keep extras together (orchestration-only sync removes fastapi)
uv sync --extra api --extra orchestration --extra tracking --group dev

# Terminal A — worker (must stay up)
make worker

# Terminal B — 24h-style soak (48 generations)
uv run fmtrader campaign new --config configs/campaigns/trial_24h.yaml --temporal
```

Then open:
- Temporal UI: http://localhost:8233 → workflow id printed by the CLI
- MLflow: http://localhost:5001 → experiment **fmtrader** (backtests log here)
- Campaigns page: http://localhost:3000/campaigns

Control:
```bash
make pause ID=<campaign_id>
make resume ID=<campaign_id>
uv run fmtrader campaign abort <campaign_id>
uv run fmtrader campaign status <campaign_id>
uv run fmtrader campaign report <campaign_id>
```

Default `make campaign` uses `--local` (in-process) and **does not** create a Temporal workflow.

### Multi-strategy campaign

```bash
uv run fmtrader campaign new --config configs/campaigns/trial_multi_short.yaml --local
uv run fmtrader campaign report <campaign_id>
```

Searches `ema_cross`, `rsi_mean_reversion`, `macd_cross`, `bollinger_breakout`, and `supertrend_trend` via `configs/spaces/multi_family.yaml`. End-of-campaign **SUMMARY.md** (also appended to the journal) ranks by net Sharpe with DSR / cost drag / trades.

### Long multi-strategy soak (Temporal)

```bash
# Terminal A — worker must stay up (restart after code changes)
export MLFLOW_TRACKING_URI=http://127.0.0.1:5001
make worker

# Terminal B
uv run fmtrader campaign new --config configs/campaigns/trial_multi_long.yaml --temporal
```

Uses `configs/spaces/multi_family_dense.yaml` (~1k valid cells), `refine_space: false`, full bar history (`max_bars: null`), up to 2000 generations. Expect multi-day runtime. Monitor Temporal UI / `fmtrader campaign status <id>` / MLflow.

```bash
export PATH="$HOME/.local/bin:$PATH"
cd /path/to/fmengine

# Terminal A — infrastructure (if not already up)
make up

# Terminal B — API
make api
# → http://127.0.0.1:8000/docs

# Terminal C — UI
make ui
# → http://localhost:3000
```

Open **http://localhost:3000/lab** for the Manual Strategy Lab.

## Strategy Lab (B10)

1. Open http://localhost:3000/lab
2. Pick strategy (`ema_cross` or `buy_and_hold`) — form fields come from `/api/strategies/{name}/schema`
3. Pick dataset (XAUUSD bid snapshot)
4. Optionally lower **Max bars** (default 5000) for faster iteration
5. Click **Run (manual trial)**
6. Result shows MetricsBlock (Sharpe + DSR + trials + cost drag) and OutcomeBlock (win rate + expectancy)
7. Session trial counter persists in `localStorage`; every run is written to the trial registry with `source=manual`
8. Open the execution link to inspect the full manifest

CLI equivalent:

```bash
uv run fmtrader backtest run \
  --strategy ema_cross \
  --params configs/strategies/ema_cross_default.yaml \
  --dataset xauusd_1m_bid_2021-01-03_2026-08-30 \
  --lane vectorbt
```

## Useful URLs

| What | URL |
|---|---|
| Health dashboard | http://localhost:3000/ |
| Strategy Lab | http://localhost:3000/lab |
| Executions | http://localhost:3000/executions |
| Campaigns | http://localhost:3000/campaigns |
| Vault / kill-switch | http://localhost:3000/vault |
| OpenAPI docs | http://127.0.0.1:8000/docs |
| QuestDB | http://localhost:9000 |
| Temporal | http://localhost:8233 |
| MLflow | http://localhost:5001 |

## Smoke verify

```bash
export PATH="$HOME/.local/bin:$PATH"
curl -s http://127.0.0.1:8000/api/system/health | python3 -m json.tool | head
curl -s http://127.0.0.1:8000/api/datasets | python3 -m json.tool | head
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:3000/lab
make check          # unit suite
make check-integration   # API contract + SSE + paper/parity (optional)
```

## Common failures

| Symptom | Fix |
|---|---|
| `uv: command not found` | `export PATH="$HOME/.local/bin:$PATH"` (add to `~/.zshrc`) |
| UI loads but Health/Lab error | Start API: `make api` |
| `POSTGRES_USER is not set` | Create `.env` from `.env.example` with real passwords |
| Lab run is slow | Lower max bars (e.g. 2000) or ensure catalog Parquet exists |
| Volume strategy disabled | Expected on XAUUSD bid-only (`has_volume=false`) |
| Docker permission denied | Start Docker Desktop; re-run `make up` |

## Memory budget (M5 Pro 24 GB)

- Docker stack ≤ 6 GB · Ollama ≤ 8 GB · backtest workers ≤ 6 GB · OS/IDE ≥ 4 GB
- Default sweep workers: 6 (`make sweep`)
- Do not load 14B Ollama during a large sweep
