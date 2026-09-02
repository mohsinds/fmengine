# LLM routing — local-first, cloud optional

Campaign agents call LLMs by **purpose** (workflow layer). Each purpose maps to a
`provider` + `model` in campaign YAML under `llm_routing`.

## Purposes

| Purpose | Typical use | Default (all-local) |
|---------|-------------|---------------------|
| `hypothesize` | Propose strategy/param JSON | `ollama` / `qwen2.5-coder:7b` |
| `critique` | Review shortlist | `ollama` / `qwen2.5:14b-instruct-q4_K_M` |
| `select` | Survivor rationale | same 14B |
| `report` | Ingredient recipe / summary | `qwen2.5-coder:7b` |
| `mutate` / `summarize` | Reserved | 7B |

During active sweeps, 14B+ Ollama models are forced down to the 7B local client
(memory budget).

## Switching layers

```yaml
# configs/campaigns/trial_agentic_ollama.yaml
use_stub_llm: false
llm_routing:
  hypothesize: { provider: ollama, model: qwen2.5-coder:7b }
  critique: { provider: ollama, model: qwen2.5:14b-instruct-q4_K_M }
  select: { provider: ollama, model: qwen2.5:14b-instruct-q4_K_M }
  report: { provider: ollama, model: qwen2.5-coder:7b }
  # Cloud overrides:
  # critique: { provider: anthropic, model: claude-sonnet-4-5-20250929 }
  # report: { provider: openai, model: gpt-4o-mini }
```

Providers: `ollama` | `openai` | `anthropic` | `stub`.
Keys: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` in `.env`. Ollama URL: `OLLAMA_URL`
(default `http://localhost:11434`).

Budget caps in YAML still apply to paid providers (`openai_usd`, `anthropic_usd`,
`per_campaign_usd`, …). Ollama is ledgered at **$0**.

## Download models

```bash
ollama pull qwen2.5-coder:7b
ollama pull qwen2.5:14b-instruct-q4_K_M
ollama pull llama3.1:8b-instruct-q4_K_M   # optional mid-size frontier
ollama pull qwen2.5:3b                    # optional light report tier
```

Only one large model should be resident at a time on a 24 GB machine
(Ollama budget ≤ 8 GB).

## Test outside fmengine

```bash
# Interactive chat
ollama run qwen2.5-coder:7b
ollama run qwen2.5:14b-instruct-q4_K_M

# One-shot HTTP
curl http://127.0.0.1:11434/api/generate -d '{
  "model": "qwen2.5-coder:7b",
  "prompt": "Reply with one word: pong",
  "stream": false
}'

# OpenAI-compatible endpoint (Open WebUI, Continue, curl, etc.)
curl http://127.0.0.1:11434/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen2.5-coder:7b","messages":[{"role":"user","content":"ping"}]}'
```

List local models: `ollama list` or `curl http://127.0.0.1:11434/api/tags`.

## Smoke inside the repo

```bash
uv run python scripts/smoke_llm_providers.py
```

## LangSmith (optional)

Set in `.env` (never commit keys):

```
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=FMEngine
LANGSMITH_TRACING=true
```

When enabled, each `LLMRouter.complete` emits a LangSmith span.
