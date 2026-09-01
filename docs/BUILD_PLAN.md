# fmengine — Phase-by-Phase Build Plan

**Purpose:** a sequenced build plan where each phase has explicit deliverables, a test suite, a
verification procedure, hard exit criteria, and the failure modes that phase is prone to.

**Rule that governs the whole plan:** a phase is not complete until its exit criteria pass on your
machine and you have seen the actual output. "It should work" is not a completion state.

**Last revised:** 2026-08-31

---

## Global testing standards

Applied in every phase, not restated each time.

| Layer | Tool | Requirement |
|---|---|---|
| Static | `ruff`, `mypy --strict` | Zero errors on `src/` before any phase is called done |
| Unit | `pytest` | Pure logic, fast, no Docker dependency |
| Property | `hypothesis` | Numerical invariants that must hold for arbitrary valid input |
| Integration | `pytest -m integration` | Anything touching QuestDB / Postgres / Temporal / Ollama |
| Golden | fixtures under `tests/golden/` | Known-input → known-output regression guards |
| Adversarial | `tests/leakage/` | Deliberately planted bugs the system must catch |

**Coverage targets:** ≥ 90% on `data`, `features`, `backtest/validation`, `risk`. These are the modules
where a silent bug produces a plausible-looking wrong number. Lower elsewhere is acceptable.

**Test data policy:** every phase from 2 onward uses a small committed fixture (`tests/fixtures/xauusd_sample_5d.parquet`,
~7,200 bars) for fast tests, and the full dataset only in explicitly marked slow tests.

---

## Phase 0 — Repository scaffolding

### Deliverables
`pyproject.toml` (uv workspace, dependency groups), `.python-version`, `Makefile`, `.gitignore`,
`.env.example`, `pre-commit` config, `.cursor/` bundle, `docs/` with SCOPE / PLAN / FRONTEND_SPEC /
REVIEW_UI_SPEC, empty package skeleton with `__init__.py` files, `docs/adr/0000-template.md`.

### Steps
1. `uv init --python 3.12`; create the `src/fmtrader/` tree from `SCOPE.md` §6.
2. Define dependency groups: `core`, `data`, `backtest`, `ml`, `agents`, `orchestration`, `tracking`, `api`, `dev`.
3. Configure ruff (line length 100, full rule set minus noise), mypy strict, pytest markers
   (`integration`, `slow`, `leakage`).
4. Pre-commit: ruff format, ruff check, mypy, no-large-files, no-secrets.
5. `Makefile` targets per `SETUP_PROMPT.md` §12.

### Tests
- `tests/unit/test_imports.py` — every module imports cleanly with no circular dependencies.
- `tests/unit/test_package_structure.py` — asserts `core` imports nothing from `fmtrader.*`
  (the dependency-free invariant).

### Verification
```bash
make install && make check          # ruff + mypy + pytest all green on an empty suite
python -c "import fmtrader; print(fmtrader.__version__)"
```

### Exit criteria
- [ ] `make check` green
- [ ] `core` has zero internal imports (test enforces it)
- [ ] Pre-commit hooks fire on a test commit

### Failure modes to watch
Circular imports between `core` and `config` — resolve by keeping `core` free of settings.
Dependency-group bloat: if `make install` with only `core` pulls in vectorbt, the groups are wrong.

---

## Phase 1 — Infrastructure

### Deliverables
`docker-compose.yml`, `scripts/init-multiple-dbs.sh`, health-check CLI, Ollama models pulled,
memory-monitor utility, structured logging bootstrap.

### Steps
1. Bring up the stack; confirm each service's health endpoint.
2. `scripts/init-multiple-dbs.sh` creates `fmtrader`, `temporal`, `temporal_visibility`, `mlflow`.
3. Implement `fmtrader system health` — checks all six services, prints a table with latency.
4. Implement `fmtrader system resources` — memory breakdown by Docker / Ollama / Python workers
   against the 24 GB budget.
5. Install Ollama natively (Metal), pull the three models.
6. `structlog` bootstrap: JSON output, `run_id`/`campaign_id` correlation fields.

### Tests
```
tests/integration/test_infra.py
  test_questdb_reachable_and_writable
  test_postgres_all_databases_exist
  test_temporal_client_connects
  test_redis_set_get
  test_mlflow_experiment_create
  test_ollama_generates
tests/unit/test_memory_monitor.py
  test_reports_within_budget
  test_flags_breach_when_over_ceiling
tests/unit/test_logging.py
  test_correlation_id_propagates_through_context
```

### Verification
```bash
make up && sleep 30
docker compose ps                    # all healthy
fmtrader system health               # all six green
fmtrader system resources            # totals under budget
ollama run qwen2.5-coder:7b "say ok"
make check
```

### Exit criteria
- [ ] All six services healthy, restart-persistent (`docker compose restart` → still healthy)
- [ ] Memory monitor reports Docker stack < 6 GB at idle
- [ ] Ollama responds and the 14B model loads within its ceiling
- [ ] Logs emit valid JSON with correlation fields

### Failure modes
Docker Desktop's own memory allocation on macOS is separate from container limits — check
Settings → Resources. Temporal's auto-setup image needs its databases to already exist; if it crash-loops,
the init script did not run. Ollama in Docker loses Metal acceleration — it must be native.

---

## Phase 2 — Data layer

### Deliverables
`core/contracts.py`, `data/adapters/dukascopy.py`, `data/quality.py`, `data/catalog.py`,
`data/calendars.py`, `data/resample.py`, `data/contracts.py` (roll interface), ingestion CLI,
snapshot manifests, QuestDB mirror.

### Steps
1. `Bar` schema with tz-aware UTC, `instrument_class`, optional `volume`/`open_interest`/`bid`/`ask`.
2. Adapter capability declaration protocol (`has_volume`, `has_spread`, `has_open_interest`, `has_depth`,
   `session_calendar`).
3. Dukascopy adapter: epoch-ms parsing, column normalization, side tagging, capability declaration.
4. Quality gate — hard-fail and report categories per `SCOPE.md` §7.
5. Flat-bar run detection → `is_tradable` boolean column on every bar.
6. Session calendar for XAUUSD (Sun 22:00 UTC → Fri 21:00 UTC with the daily break).
7. Catalog writer: partitioned Parquet + snapshot manifest with content hash.
8. QuestDB mirror with idempotent upsert.
9. Futures roll interface (pass-through for spot).
10. Resampling: 1m → 5m/15m/1h, session-aware, with correct OHLC aggregation.

### Tests
```
tests/unit/test_contracts.py
  test_bar_rejects_naive_datetime
  test_bar_rejects_ohlc_violation
  test_optional_fields_are_none_not_zero
tests/unit/test_dukascopy_adapter.py
  test_epoch_ms_parsed_as_milliseconds_not_seconds     # a classic 1000x bug
  test_capabilities_declare_no_volume_no_spread
  test_missing_column_raises_named_error
tests/unit/test_quality.py
  test_detects_duplicate_timestamps
  test_detects_non_monotonic_timestamps
  test_detects_ohlc_invariant_violation
  test_classifies_weekend_gap_correctly
  test_classifies_holiday_gap_correctly
  test_flags_anomalous_gap
  test_detects_flat_bar_runs
  test_mad_outlier_detection_flags_spike
  test_coverage_table_sums_to_total
tests/unit/test_resample.py
  test_1m_to_5m_ohlc_aggregation_correct
  test_resample_respects_session_boundaries
  test_resample_never_creates_bars_from_gaps
tests/property/test_catalog_roundtrip.py
  test_write_read_frame_equality             # hypothesis-generated frames
  test_content_hash_stable_across_writes
  test_content_hash_changes_when_data_changes
tests/integration/test_ingest_e2e.py
  test_full_ingest_produces_manifest
  test_questdb_row_count_matches_parquet
  test_reingest_is_idempotent                # run twice, no duplicates
```

### Verification
```bash
fmtrader data ingest --adapter dukascopy \
  --path download/xauusd-m1-bid-2021-01-01-2026-08-31.csv \
  --symbol XAUUSD --timeframe 1m --instrument-class spot_cfd --side bid

fmtrader data quality --dataset xauusd_1m_bid_2021-01-01_2026-08-31   # coverage table
fmtrader data ingest ... # again → idempotent, no duplicates
```

**Manual check that no test replaces:** open the coverage table and read it. Then pick 10 random
timestamps and compare bar values against the raw CSV by hand. Automated tests confirm the code does
what you told it; this confirms you told it the right thing.

### Exit criteria
- [ ] Full dataset ingested; row counts reconcile Parquet ↔ QuestDB
- [ ] Coverage table printed and visually sane (no unexplained month at 40%)
- [ ] 10 bars hand-verified against the raw file
- [ ] Manifest records `has_volume: false`, `has_spread: false`, `side: bid`
- [ ] `is_tradable` correctly false across a known weekend
- [ ] Re-ingest is idempotent
- [ ] Ingest of the full file completes in < 5 minutes

### Failure modes
Epoch-ms read as seconds (dates land in 1970) — the named test exists for this reason.
Timezone applied twice. Resampling across the daily session break creating phantom bars. Content hash
computed over a dict with non-deterministic ordering — sort keys before hashing.

---

## Phase 3 — Features & labeling

### Deliverables
Indicator registry with capability gating, indicator library, regime features, triple-barrier labeling,
meta-labeling, sample weights, versioned feature store.

### Steps
1. `@register_indicator` decorator carrying `requires`, `requires_volume`, `min_lookback`, `params_schema`.
2. Implement trend, momentum, volatility, session categories. Volume and microstructure categories
   registered but gated off.
3. Quantile volatility regime with **trailing-only** ranking and config-fixed bucket edges.
4. Triple-barrier labeling with ATR-scaled barriers.
5. Meta-labeling scaffold.
6. Sample weights from label uniqueness.
7. Feature pipeline: YAML definition → validation against dataset capabilities → build → store.
8. Feature store with `(dataset_id, feature_set_version)` keying and definition hashing.

### Tests
```
tests/unit/test_indicator_registry.py
  test_volume_indicator_raises_on_volumeless_dataset      # THE critical gating test
  test_error_names_dataset_and_missing_capability
  test_insufficient_lookback_raises
tests/unit/test_indicators_<category>.py         # one file per category
  test_<name>_matches_reference_values
  test_<name>_warmup_null_count_equals_min_lookback
  test_<name>_no_lookahead                       # truncation test, see below
  test_<name>_handles_constant_series
  test_<name>_handles_single_row
tests/property/test_indicator_invariants.py
  test_rsi_bounded_0_100
  test_atr_non_negative
  test_bb_ordering_lower_le_mid_le_upper
  test_donchian_contains_close
tests/unit/test_labeling.py
  test_triple_barrier_first_touch_wins
  test_time_barrier_applies_when_no_touch
  test_barriers_scale_with_atr
  test_no_label_uses_future_beyond_its_own_window
  test_sample_weights_sum_sensibly_under_overlap
tests/unit/test_feature_pipeline.py
  test_yaml_definition_produces_deterministic_hash
  test_unavailable_feature_fails_before_any_computation   # fail fast, not mid-build
tests/leakage/test_feature_leakage.py
  test_planted_centered_window_is_caught
  test_planted_future_shift_is_caught
```

**The truncation test — use it for every indicator:**
```python
full = indicator(df)                    # compute on the whole series
trunc = indicator(df.head(n + 1))       # compute on data ending at bar n
assert full[n] == trunc[n]              # value at n must not depend on n+1..end
```
This catches look-ahead more reliably than code review.

### Verification
```bash
fmtrader features build --dataset <id> --set configs/features/baseline.yaml
fmtrader features list --dataset <id>          # availability + unavailable-with-reason
pytest tests/property -q
```

### Exit criteria
- [ ] All indicator tests pass, including the truncation test for every indicator
- [ ] Requesting VWAP on the gold dataset raises an error naming the dataset and `has_volume`
- [ ] Full feature build (~2M bars, ~50 features) completes < 10 min, peak memory < 4 GB
- [ ] Feature set hash is stable across runs and changes when the YAML changes
- [ ] Planted leakage bugs are caught

### Failure modes
Pandas `rolling(center=True)` slipping in. Warmup nulls forward-filled "for convenience" — this
silently creates look-ahead. Regime bucket edges fit on the full sample (leakage). Memory blowup from
materializing all features as float64 when float32 suffices.

---

## Phase 4 — Backtesting, costs, and the Execution Recorder ★

★ The `ExecutionRecorder` belongs here, not in the observability phase. Retrofitting provenance onto
an engine that has already run a campaign makes that campaign unreviewable.

### Deliverables
vectorbt lane runner, NautilusTrader lane runner, cost models, metrics suite, **`ExecutionRecorder`**,
signal-funnel instrumentation, per-trade enrichment (MAE/MFE/exit reason/session/regime).

### Steps
1. `ExecutionRecorder` context manager: captures the manifest at start, appends step entries, writes
   atomically at end, writes a partial record with a failure marker on crash.
2. vectorbt runner with chunked sweeps and a configurable worker pool (default 6).
3. NautilusTrader runner with venue config and a matching cost model.
4. Cost model: spread (measured or assumed constant, session-multiplied), commission, slippage
   (base + volatility-scaled), applied identically in both lanes.
5. Metrics suite per `backtest-review` skill.
6. Funnel instrumentation: raw signals → regime filter → gate → risk limits → orders → fills, with
   drop reasons.
7. Per-trade enrichment recorded at trade close, not reconstructed later.
8. Cost-sensitivity sweep at 1.0× / 1.5× / 2.0×.

### Tests
```
tests/unit/test_costs.py
  test_spread_applied_both_sides_of_round_trip
  test_session_multiplier_widens_offhours_spread
  test_slippage_scales_with_volatility
  test_zero_cost_config_rejected_when_spread_unmeasured   # guard against silent zero
tests/unit/test_metrics.py
  test_sharpe_matches_hand_computed_on_fixture
  test_max_drawdown_and_duration_correct
  test_profit_factor_handles_zero_losses
  test_cost_drag_equals_gross_minus_net_over_gross
tests/unit/test_execution_recorder.py
  test_manifest_captures_all_required_sections
  test_incomplete_manifest_marked_and_excluded_from_promotion
  test_crash_writes_partial_record_with_failure_point
  test_record_is_append_only
tests/unit/test_funnel.py
  test_funnel_counts_are_monotonically_non_increasing
  test_drop_reasons_sum_to_difference_between_stages
tests/integration/test_lane_parity.py
  test_buy_and_hold_net_return_matches_across_lanes       # within tolerance
  test_simple_ema_cross_trade_count_matches_across_lanes
  test_trade_directions_match_across_lanes
tests/leakage/test_backtest_leakage.py
  test_signal_bar_close_fill_is_rejected
  test_same_bar_entry_and_exit_is_rejected
  test_planted_future_peeking_strategy_is_caught
tests/unit/test_trade_enrichment.py
  test_mae_mfe_computed_correctly_on_fixture
  test_exit_reason_classified_correctly            # target / stop / time / signal
```

### Verification
```bash
fmtrader backtest run --strategy ema_cross --params configs/strategies/ema_cross_default.yaml \
  --dataset <id> --lane vectorbt
fmtrader backtest run --strategy ema_cross --params ... --lane nautilus
fmtrader execution show <execution_id>     # manifest + steps + funnel print cleanly
fmtrader backtest sweep --strategy ema_cross --space configs/spaces/ema_cross.yaml --max 200
```

### Exit criteria
- [ ] Buy-and-hold nets identical across lanes within tolerance
- [ ] A deliberately look-ahead-biased strategy is caught and rejected
- [ ] Every execution writes a complete manifest; incomplete ones are marked
- [ ] Funnel counts are internally consistent
- [ ] Cost drag reported as % of gross on every run
- [ ] 1,000-config sweep completes < 15 min on 6 workers, memory within budget
- [ ] Zero-spread config is rejected on a dataset with `has_spread: false`

### Failure modes
The two lanes disagreeing and the difference being rationalized rather than diagnosed — a large
vectorbt→Nautilus gap means the fast lane is lying about fills, and that is a finding, not noise.
Vectorbt sweeps consuming all memory because chunking was skipped. MAE/MFE computed from bars after
the fact rather than captured during simulation.

---

## Phase 5 — Validation & anti-overfitting ★★

★★ The most important phase. Nothing downstream is trustworthy without it.

### Deliverables
Purged/embargoed CV, walk-forward, regime segmentation, trial registry, DSR, PBO via CSCV,
holdout vault with token guard, adversarial leakage suite, gate evaluation and verdict assignment.

### Steps
1. Purged K-fold with embargo, driven by label windows.
2. Walk-forward, rolling and anchored, with per-window reporting.
3. Regime segmentation (2021 / 2022 / 2023–24 / 2025–26).
4. Trial registry in Postgres: every evaluated config with params, metrics, source, timestamp.
5. Deflated Sharpe Ratio using the registry's trial count.
6. PBO via CSCV.
7. **Holdout vault:** catalog reader raises unless a `HoldoutUnlockToken` is supplied; unlock is
   logged, irreversible per strategy, and single-use.
8. Gate evaluator producing `NOISE` / `FRAGILE` / `CANDIDATE` / `VALIDATED`.
9. Robustness checks: top-5-trade removal, session split, parameter-neighborhood stability.

### Tests
```
tests/unit/test_purged_cv.py
  test_no_train_sample_overlaps_test_label_window
  test_embargo_excludes_correct_bar_count
  test_folds_are_contiguous_in_time
  test_purging_reduces_train_size_as_expected
tests/unit/test_walkforward.py
  test_rolling_windows_do_not_overlap_test_sets
  test_anchored_train_set_grows_monotonically
  test_per_window_metrics_reported
tests/unit/test_trial_registry.py
  test_every_evaluated_config_is_written
  test_duplicate_config_detected_by_hash
  test_trial_count_per_strategy_accurate
  test_manual_and_agent_runs_share_the_registry
tests/unit/test_dsr_pbo.py
  test_dsr_decreases_as_trial_count_increases
  test_dsr_matches_reference_on_known_input
  test_pbo_near_one_for_pure_noise_strategies      # the sanity check that matters
  test_pbo_low_for_a_synthetic_real_edge
tests/unit/test_holdout_vault.py
  test_catalog_read_without_token_raises
  test_no_public_api_path_returns_holdout_data
  test_unlock_is_logged_with_justification
  test_second_unlock_for_same_strategy_rejected
tests/leakage/test_adversarial_suite.py
  test_catches_shifted_label_leakage
  test_catches_centered_rolling_window
  test_catches_scaler_fit_on_full_series
  test_catches_same_bar_entry_exit
  test_catches_future_regime_label
  test_catches_target_encoded_with_future_data
tests/unit/test_gates.py
  test_noise_verdict_when_dsr_negative
  test_fragile_verdict_when_edge_dies_at_1_5x_costs
  test_candidate_requires_all_gates_passed
  test_validated_requires_holdout_consumed
```

**The noise calibration test is the one that proves the subsystem works:** generate random-signal
strategies, sweep 1,000 configs, take the best. Its raw Sharpe will look respectable. The system must
assign it `NOISE` with a PBO near 1. If it does not, the validation layer is decorative.

### Verification
```bash
fmtrader validate run --execution <id> --cv purged --folds 6 --embargo 60
fmtrader validate walkforward --execution <id> --method rolling
fmtrader registry count --strategy ema_cross
fmtrader registry deflate --strategy ema_cross
pytest tests/leakage -v                    # every planted bug caught
fmtrader validate noise-calibration --trials 1000    # must return NOISE
```

### Exit criteria
- [ ] Every planted leakage bug in the adversarial suite is caught
- [ ] Noise calibration returns `NOISE` with PBO > 0.8
- [ ] No code path returns holdout data without a logged token
- [ ] Second unlock attempt for the same strategy is rejected
- [ ] DSR demonstrably decreases as trial count rises
- [ ] Trial registry captures manual and automated runs identically

### Failure modes
Embargo applied on one side only. PBO implemented but never sanity-checked against noise — hence the
calibration test. The holdout guard enforced at the API layer but bypassable through the catalog —
test the catalog directly. Trial registry writes skipped for "exploratory" runs, which corrupts every
subsequent deflation.

---

## Phase 6 — Provider architecture (news, sentiment, fundamentals)

See `docs/PROVIDER_ARCHITECTURE.md` for the full design. Build the framework here even though the
concrete providers arrive later — retrofitting point-in-time correctness is far harder than designing for it.

### Deliverables
`FeatureProvider` protocol, point-in-time record contract, as-of join engine, provider registry,
optional-dependency isolation, a reference `NullProvider` and a `SyntheticNewsProvider` for testing.

### Steps
1. Define the `FeatureProvider` protocol (capabilities, availability window, `fetch`, `to_features`).
2. `PointInTimeRecord` with `event_time`, `available_time`, `ingestion_time`, `revision_of`.
3. As-of join engine: aligns sparse irregular records to regular bars **on `available_time`**, never
   `event_time`.
4. Alignment strategies: last-known-value, decay with half-life, rolling aggregation, count-in-window.
5. Provider registry with config-driven composition and graceful absence.
6. `SyntheticNewsProvider` producing deterministic fake events for testing the join semantics.

### Tests
```
tests/unit/test_provider_protocol.py
  test_provider_declares_capabilities
  test_core_pipeline_runs_with_zero_providers_registered
  test_missing_optional_dependency_disables_provider_without_crashing
tests/unit/test_point_in_time.py
  test_record_requires_event_and_available_time
  test_available_time_never_precedes_event_time
  test_revision_does_not_overwrite_original
tests/unit/test_asof_join.py
  test_join_uses_available_time_not_event_time        # THE critical test
  test_record_published_after_bar_is_not_visible
  test_publication_lag_parameter_respected
  test_decay_halflife_produces_expected_weights
  test_sparse_records_dense_bars_no_forward_leak
tests/leakage/test_provider_leakage.py
  test_planted_event_time_join_is_caught
  test_restated_value_used_in_history_is_caught
  test_backfilled_record_without_available_time_is_rejected
```

### Verification
```bash
fmtrader providers list                 # shows registered + available/unavailable with reason
fmtrader features build --set configs/features/with_synthetic_news.yaml
fmtrader providers validate --provider synthetic_news --dataset <id>
```

### Exit criteria
- [ ] Core pipeline runs identically with zero providers registered
- [ ] As-of join provably uses `available_time`; the planted `event_time` join is caught
- [ ] A record published after a bar is invisible to that bar
- [ ] Removing a provider's dependency disables it cleanly rather than crashing the build

---

## Phase 7 — Agentic research pipeline

### Deliverables
Temporal workflows and activities, LangGraph nodes, LLM router, budget governor, cost ledger,
research journal, campaign CLI.

### Steps
1. `ResearchCampaignWorkflow` with `pause` / `resume` / `adjust_budget` / `abort` signals and
   per-generation checkpoints.
2. Activities: hypothesize, validate proposal, fast sweep, shortlist, fidelity, critique, select, journal.
3. LangGraph graph wiring the nodes with campaign state.
4. LLM router: tier selection, memory check before local model load, fallback under pressure.
5. Budget governor: pre-call estimation, three-level caps, refusal, ledger, graceful degradation.
6. Journal writer producing Markdown per generation.
7. Proposal validation: structured configs against schema only; never `exec`.

### Tests
```
tests/unit/test_budget_governor.py
  test_refuses_call_that_would_breach_campaign_cap
  test_refuses_call_that_would_breach_daily_cap
  test_degrades_to_local_tier_on_exhaustion_without_crashing
  test_ledger_records_every_call
  test_cost_estimate_precedes_call
tests/unit/test_llm_router.py
  test_falls_back_to_7b_when_memory_below_threshold
  test_never_loads_14b_during_active_sweep
  test_frontier_tier_only_used_for_gating_nodes
tests/unit/test_proposal_validation.py
  test_invalid_schema_proposal_rejected_not_repaired
  test_duplicate_config_rejected_against_registry
  test_proposal_containing_code_is_rejected
  test_proposal_requesting_holdout_is_rejected
tests/integration/test_campaign_workflow.py
  test_campaign_completes_short_run
  test_pause_signal_halts_after_current_activity
  test_resume_continues_from_checkpoint
  test_worker_restart_mid_campaign_resumes_correctly    # kill the worker, restart, verify
  test_abort_leaves_consistent_state
  test_journal_written_per_generation
```

**The durability test that matters:** start a campaign, let it reach generation 2, `docker compose
restart temporal` and kill the worker process, restart both, and confirm it resumes at the right point
with no duplicated or lost work.

### Verification
```bash
fmtrader worker start &
fmtrader campaign new --config configs/campaigns/trial_24h.yaml
fmtrader campaign status <id>
fmtrader campaign pause <id>     # then restart the machine
fmtrader campaign resume <id>
fmtrader campaign report <id>    # journal renders, decisions legible
```

### Exit criteria
- [ ] 24-hour trial campaign completes
- [ ] Pause → machine restart → resume works with no lost or duplicated generations
- [ ] Budget caps enforced; breach attempt refused and logged
- [ ] Every proposal validated; none executed as code
- [ ] Journal explains every generation's decision in readable prose
- [ ] Agent cannot reach holdout data (test asserts it)

### Failure modes
Temporal activities exceeding their timeout during long sweeps — set generous activity timeouts and
heartbeat. Non-deterministic code inside workflow functions (random, time, IO) — all of that belongs
in activities. Budget checked after the call instead of before.

---

## Phase 8 — Risk & sizing

### Deliverables
Fractional Kelly, volatility targeting, probability calibration, conformal gate, limits service,
kill-switch.

### Tests
```
tests/unit/test_sizing.py
  test_fractional_kelly_matches_formula
  test_kelly_capped_by_max_risk_per_trade
  test_kelly_rejects_uncalibrated_probabilities       # must refuse, not silently proceed
  test_vol_targeting_scales_inversely_with_realized_vol
tests/unit/test_calibration.py
  test_isotonic_improves_brier_score_on_fixture
  test_calibration_curve_within_tolerance
tests/unit/test_conformal.py
  test_empirical_coverage_matches_nominal_alpha
  test_wide_interval_triggers_skip
  test_gate_rejects_high_uncertainty_high_probability_signal
tests/unit/test_limits.py
  test_daily_loss_limit_halts_trading
  test_drawdown_limit_halts_trading
  test_consecutive_loss_breaker_fires
  test_kill_switch_blocks_all_orders
  test_limits_evaluated_between_signal_and_execution   # architectural assertion
```

### Exit criteria
- [ ] Conformal empirical coverage matches nominal α within tolerance
- [ ] Kelly refuses uncalibrated inputs
- [ ] Kill-switch blocks orders and is reachable independently of the strategy process
- [ ] Limits demonstrably sit between signal and execution, not inside strategy code

---

## Phase 9 — Review UI backend & frontend

Per `docs/REVIEW_UI_SPEC.md`. Build order R1→R8.

### Tests
```
tests/integration/test_api_contract.py
  test_openapi_schema_valid
  test_every_documented_endpoint_responds
  test_execution_manifest_endpoint_returns_all_sections
  test_equity_endpoint_downsamples_to_requested_points
  test_breakdown_endpoint_supports_all_dimensions
tests/integration/test_sse.py
  test_campaign_stream_emits_expected_events
  test_events_are_batched_under_throttle_threshold
  test_client_reconnect_resumes_stream
```
Frontend: Vitest for components, Playwright for the critical paths — open an execution, read its
manifest, drill to a trade; pause and resume a campaign; attempt promotion with a failing DSR gate
and confirm it is blocked.

### Exit criteria
- [ ] Any execution can be opened and its full ingredients reconstructed without guessing
- [ ] Win rate never renders without expectancy beside it
- [ ] Equity curves with 2M underlying points render < 500 ms
- [ ] Promotion blocked when DSR gate fails

---

## Phase 10 — CME futures onboarding

### Tests
```
tests/unit/test_databento_adapter.py
  test_capabilities_declare_volume_and_open_interest
  test_contract_symbol_parsed_to_root_month_year
tests/unit/test_continuous_contracts.py
  test_panama_adjustment_preserves_price_differences
  test_ratio_adjustment_preserves_returns
  test_roll_uses_only_information_available_at_roll_date   # leakage guard
  test_volume_crossover_roll_selects_correct_contract
  test_raw_contracts_retained_alongside_continuous
tests/integration/test_futures_revalidation.py
  test_volume_features_become_available
  test_previously_gated_indicators_now_compute
```

### Exit criteria
- [ ] GC/MGC ingested with real volume and open interest
- [ ] Continuous series validated against known roll dates
- [ ] Roll adjustment provably free of future information
- [ ] Strategies that survived on XAUUSD re-validated on futures — **expect the results to change**

---

## Phase 11 — Execution & paper trading

### Tests
```
tests/unit/test_broker_adapter.py
  test_client_order_id_is_idempotent
  test_duplicate_submission_does_not_double_fill
tests/integration/test_ibkr_paper.py
  test_connects_and_subscribes
  test_order_lifecycle_submit_fill_report
  test_reconciliation_after_forced_disconnect
  test_kill_switch_cancels_open_orders
tests/integration/test_live_backtest_parity.py
  test_same_strategy_code_path_in_both_modes
  test_signal_sequence_matches_replayed_backtest
```

### Exit criteria
- [ ] Paper trades execute on the identical code path as backtest
- [ ] Reconciliation survives a forced disconnect with no phantom positions
- [ ] Kill-switch cancels open orders within a defined bound

---

## Cross-cutting checkpoints

Run these at the end of every phase from 4 onward, not only at the end:

| Check | Command |
|---|---|
| Full suite | `pytest -q` |
| Leakage suite | `pytest tests/leakage -v` |
| Static | `ruff check src && mypy src` |
| Reproducibility | re-run a stored execution by ID → identical metrics |
| Memory | `fmtrader system resources` during the heaviest operation |
| Registry integrity | trial count equals the number of executions written |

---

## Phase dependency graph

```
0 ──> 1 ──> 2 ──> 3 ──> 4 ──> 5 ──┬──> 7 ──> 8 ──> 11
                            │      │
                            │      └──> 9
                            └──> 6 ──────┘
                                         └──> 10
```

**Hard rule:** 5 before 7. An agent on an unvalidated harness manufactures false confidence at scale.
**Recommended:** 6 before 7, so the agent can propose sentiment features from day one rather than
requiring a campaign redesign later.

---

## Estimated effort

| Phase | Effort | Note |
|---|---|---|
| 0 Scaffolding | 1 day | |
| 1 Infrastructure | 1–2 days | Docker/Ollama friction on macOS |
| 2 Data | 4–6 days | Quality gate is more work than it appears |
| 3 Features | 5–8 days | Indicator count drives this |
| 4 Backtest + Recorder | 6–9 days | Lane parity is the slow part |
| 5 Validation ★ | 6–9 days | Do not compress this |
| 6 Providers | 3–4 days | Framework only |
| 7 Agentic | 7–10 days | Temporal determinism rules take adjustment |
| 8 Risk | 3–4 days | |
| 9 Review UI | 10–15 days | Backend + frontend |
| 10 CME | 4–6 days | Plus data cost |
| 11 Execution | 5–8 days | |

Roughly 11–17 weeks of focused solo work to Phase 11. Phases 0–5 — the trustworthy research core —
are about 4–6 weeks and are the part worth doing carefully.