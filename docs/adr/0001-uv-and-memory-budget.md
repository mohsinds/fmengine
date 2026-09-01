# ADR 0001 — uv + Python 3.12 and a hard memory budget

**Status:** Accepted  
**Date:** 2026-08-31  
**Deciders:** fmengine Phase 1

## Context

The research/execution stack must stay reproducible on Apple Silicon with **24 GB unified
memory** shared by macOS, Docker, Ollama, and backtest workers. Dependency resolution must be
fast and lockfile-based.

## Decision

- Use **Python 3.12** managed by **uv** (`uv.lock`) with a `src/fmtrader` package layout.
- Keep runtime **core** dependencies lean; put vectorbt/Nautilus/LangGraph/etc. in optional
  extras installed only when that phase needs them.
- Cap the Docker stack at ~**6 GB**, reserve ~**8 GB** for a single local LLM, and ~**6 GB** for
  backtest workers (default 6 × ~1 GB), leaving ≥**4 GB** for macOS + Cursor.

## Consequences

- `make install` syncs core + dev only in Phase 1; later phases add extras explicitly.
- Memory monitor (`fmtrader system resources`) treats Docker > 6 GB idle as a budget breach.
- Ollama must run **natively** (Metal), never inside Docker.
