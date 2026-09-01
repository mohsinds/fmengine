# ADR 0002 — QuestDB health and import mounts

**Status:** Accepted  
**Date:** 2026-08-31  
**Deciders:** fmengine Phase 1

## Context

QuestDB 8.2.1 does not expose `/status` (404). The image also lacks `curl`, so a
compose healthcheck that shells out to `curl` always fails. Separately, bind-mounting
`./data/catalog` directly onto QuestDB's import root as `:ro` prevents the process from
creating that directory at boot (`Could not create the default import directory`).

## Decision

- Probe readiness via HTTP `/ping` (204) from the host CLI.
- Use bash `/dev/tcp/127.0.0.1/9000` for the container healthcheck.
- Keep only the named `questdb_data` volume in Phase 1; defer catalog COPY mounts to
  Phase 2 with a writable import parent directory.

## Consequences

- `fmtrader system health` and compose agree on QuestDB liveness.
- Phase 2 ingest-to-QuestDB must reintroduce an import mount carefully (writable parent).
