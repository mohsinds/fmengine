# LLM routing — local-first, cloud optional

Campaign agents call LLMs by **purpose** (workflow layer). Each purpose maps to a
`provider` + `model` in campaign YAML under `llm_routing`.

## Purposes

| Purpose | Typical use | Compact local | Large research profile |
|---------|-------------|----------------|------------------------|
| `hypothesize` | Propose strategy/param JSON | `qwen2.5-coder:7b` | `gpt-oss:20b` |
| `critique` | Review shortlist | `qwen2.5:14b-instruct-q4_K_M` | `kimi-k2.6:cloud` → `qwen3.8:27b` |
| `select` | Survivor rationale | same 14B | same kimi / qwen fallback |
| `report` | Ingredient recipe / summary | 7B | `qwen3.8:27b` |
| `mutate` / `summarize` | Reserved | 7B | gpt-oss / 7B |

During an active vectorbt sweep (`router.sweep_active=True`), heavy local Ollama
models are forced down to the compact 7B client so workers keep RAM. LLM calls
around hypothesize / critique / ingredients run with `sweep_active=False` and
unload between heavy locals (`unload_ollama_model` / `keep_alive=0`).

## Providers

`ollama` | `ollama_cloud` | `openai` | `anthropic` | `stub`

- **ollama** — local Metal HTTP (`OLLAMA_URL`, default `http://localhost:11434`)
- **ollama_cloud** — same generate API; `OLLAMA_CLOUD_URL` (defaults to local host
  once `ollama signin` / cloud enabled). Optional `OLLAMA_API_KEY`. Layers may
  declare `fallback:` to a local model when cloud auth is missing.
- Paid keys: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` in `.env`

Budget caps still apply to paid providers. Ollama (local + cloud ledger) is **$0**.

## Compact campaign

```yaml
# configs/campaigns/trial_agentic_ollama.yaml
use_stub_llm: false
llm_routing:
  hypothesize: { provider: ollama, model: qwen2.5-coder:7b }
  critique: { provider: ollama, model: qwen2.5:14b-instruct-q4_K_M }
  select: { provider: ollama, model: qwen2.5:14b-instruct-q4_K_M }
  report: { provider: ollama, model: qwen2.5-coder:7b }
```

## Large research profile

```yaml
# configs/campaigns/trial_agentic_large.yaml
workers: 2
use_agent_memory: true
allow_ingredient_proposals: true
llm_routing:
  hypothesize: { provider: ollama, model: gpt-oss:20b }
  critique:
    provider: ollama_cloud
    model: kimi-k2.6:cloud
    fallback: { provider: ollama, model: qwen3.8:27b }
  select:
    provider: ollama_cloud
    model: kimi-k2.6:cloud
    fallback: { provider: ollama, model: qwen3.8:27b }
  report: { provider: ollama, model: qwen3.8:27b }
```

On 24 GB unified memory, treat 20B/27B as **one resident at a time**. Raise
`MEMORY_BUDGET_OLLAMA_GB` (e.g. 18) for this profile; keep Docker workers low.

## Download models

```bash
# Compact defaults
ollama pull qwen2.5-coder:7b
ollama pull qwen2.5:14b-instruct-q4_K_M

# Large research profile
ollama pull gpt-oss:20b
ollama pull qwen3.8:27b
# kimi-k2.6:cloud via Ollama Cloud (after `ollama signin` / cloud enabled)
ollama pull kimi-k2.6:cloud
```

## Agent memory (not fine-tuning)

With `use_agent_memory: true`, hypothesize / critique / ingredient prompts receive a
retrieval block from `TrialRegistry` + journal traces (`build_agent_memory`). Weights
are never updated. Every proposed config still passes `validate_proposal` + registry
dedupe (multiple-testing intact).

## Smoke

```bash
uv run python scripts/smoke_llm_providers.py
```

Large tags are soft-checked: missing `kimi-k2.6:cloud` auth fails that check only.
