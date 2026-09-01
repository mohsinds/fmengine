# /campaign

Configure, launch, inspect, or control a long-running agentic research campaign.

**Usage:** `/campaign new`, `/campaign status`, `/campaign pause`, `/campaign resume`, `/campaign report`

## Pre-flight checks — refuse to launch if any fail
- [ ] Validation subsystem exists and its leakage tests pass (Phase 5 complete)
- [ ] Trial registry table exists and is writable
- [ ] Holdout vault is locked and the vault guard test passes
- [ ] Cost model configured with a non-zero spread assumption for this dataset
- [ ] Budget caps set: per campaign, per generation, per day, per provider
- [ ] Temporal worker running and reachable
- [ ] Ollama reachable and the routed local model loads within the memory budget
- [ ] Disk headroom ≥ 100 GB for artifacts

## `new` — campaign config to confirm with me before launching
```yaml
campaign_id: <slug>
dataset_id: <from snapshot manifest>
universe: [XAUUSD]
timeframe: 1m
generations: <int>
population_per_generation: <int>
fast_lane_budget: <max configs per generation>
fidelity_lane_budget: <max shortlist size>
usd_budget: {campaign: <n>, per_generation: <n>, per_day: <n>}
wall_clock_limit_hours: <n>
gates: {min_dsr: 0.0, max_pbo: 0.5, cost_multiplier_test: 1.5}
parallel_workers: 6
```

## `status`
Report: current generation, elapsed wall clock, configs evaluated, best net Sharpe with its DSR and
trial count, USD spent vs cap, memory pressure, and the last journal entry's decision rationale.

## `report`
Render the campaign journal as Markdown: generation-by-generation hypotheses, parameters, net metrics,
survivor selection reasoning, search-space evolution, and total spend. Then give your own honest
assessment of whether anything found is likely to be a real edge or is consistent with noise given the
trial count. Do not oversell results.
