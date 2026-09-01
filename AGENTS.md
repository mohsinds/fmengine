# fmengine

Trading engine workspace for FM Trader. Prefer small, reversible changes and keep market-data handling explicit and testable.

## Project layout

- `download/` — historical market data CSVs (e.g. XAUUSD M1 bid)
- `.cursor/` — Cursor MCP, rules, skills, commands, and agents

## Working agreements

- Do not commit secrets, tokens, or raw credential files
- Treat large CSV downloads as data artifacts; avoid rewriting them unless asked
- Prefer clear module boundaries: data ingest, signals/strategy, execution, risk
- When touching GitHub (issues, PRs, releases), use the configured GitHub MCP tools

## GitHub MCP

Requires `GITHUB_PERSONAL_ACCESS_TOKEN` in the environment Cursor launches with.
Create a classic or fine-grained PAT with `repo` (and `read:org` if needed), then restart Cursor.
