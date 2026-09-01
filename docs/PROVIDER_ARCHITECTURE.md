# fmengine — Provider Architecture

**Purpose:** how news, sentiment, fundamentals, and any other external data plug into the feature
pipeline without modifying core code, and without introducing look-ahead bias.

**Build timing:** the *framework* is Phase 6, before the agentic pipeline. The concrete providers come
later. Designing point-in-time correctness in from the start is far cheaper than retrofitting it.

**Last revised:** 2026-08-31

---

## 1. The problem this solves

Technical indicators are easy: they derive from bars you already have, on the same regular grid, with
no ambiguity about when a value became knowable.

External data is not:

| Property | Technical indicators | News / sentiment | Fundamentals |
|---|---|---|---|
| Timing | Regular, aligned to bars | Irregular, bursty | Quarterly, scheduled but with lag |
| Availability | Immediate at bar close | Publication time ≠ event time | Report date ≠ period end |
| Revisions | None | Corrections, retractions | **Restatements — the classic trap** |
| Density | One value per bar | Zero to hundreds per bar | One value per quarter |
| Coverage | Complete | Sparse, uneven across symbols | Complete but delayed |

Each of those differences is a way to accidentally leak the future into your backtest. The architecture
exists to make the correct thing the default and the incorrect thing hard to express.

---

## 2. The point-in-time contract

Every external record carries **three timestamps**. This is the foundation; everything else follows.

```python
class PointInTimeRecord(BaseModel):
    event_time: datetime        # when the thing happened
    available_time: datetime    # when it first became knowable to a trader
    ingestion_time: datetime    # when we stored it
    revision_of: str | None     # id of the record this supersedes, if any
    payload: dict
```

**The rule that governs everything:**

> A record may influence a bar at time `t` **if and only if** `available_time <= t`.
> Never `event_time`. Never `ingestion_time`.

Examples of the gap that makes this necessary:

| Scenario | `event_time` | `available_time` | Gap |
|---|---|---|---|
| Fed decision | 18:00 UTC announcement | 18:00:03 (wire latency) | seconds |
| Earnings release | Quarter ended Mar 31 | Reported Apr 28 | 4 weeks |
| Restated earnings | Quarter ended Mar 31 | Restatement filed Nov 12 | **7 months** |
| COT report | Positions as of Tuesday | Published Friday 15:30 ET | 3 days |
| Sentiment score | Article published 09:14 | Scored and available 09:14 | none, if scored live |

The restatement row is why fundamentals leak so easily. If your vendor gives you a single "Q1 2024
revenue" figure, and that figure is the *restated* one, then every backtest bar from April 2024 onward
is using a number nobody had until November. Backtests built this way look excellent and fail live.

### Revisions are additive, never destructive

A correction creates a **new record** with a later `available_time` and `revision_of` pointing at the
original. The original stays. At any historical bar, the join picks whichever version was current
*then*. This is the only way to reproduce what you would actually have known.

---

## 3. The provider protocol

Every source of features — technical, sentiment, news, fundamentals, alternative — implements one
interface. The feature pipeline does not know or care which kind it is handling.

```python
class FeatureProvider(Protocol):
    name: str
    kind: Literal["technical", "sentiment", "news", "fundamental", "macro", "alternative"]
    optional: bool                       # True → core must run fine without it

    def capabilities(self) -> ProviderCapabilities: ...
    def availability(self, symbol: str) -> DateRange | None: ...
    def fetch(self, symbol: str, start: datetime, end: datetime) -> Iterable[PointInTimeRecord]: ...
    def feature_specs(self) -> list[FeatureSpec]: ...
    def health(self) -> ProviderHealth: ...


class ProviderCapabilities(BaseModel):
    symbols: list[str] | Literal["*"]
    asset_classes: list[str]
    min_granularity: str                 # "1m", "1d", "quarterly"
    has_revisions: bool
    typical_publication_lag: timedelta
    requires_credentials: bool
    rate_limit: RateLimit | None


class FeatureSpec(BaseModel):
    name: str                            # "sentiment_score_ewm_60m"
    dtype: Literal["float", "int", "bool", "category"]
    alignment: AlignmentStrategy
    lookback_required: timedelta
    null_policy: Literal["null", "zero", "last_known", "fail"]
```

### Optionality is structural

A provider marked `optional: true` must satisfy:

1. The core pipeline runs identically when it is not registered
2. Its Python dependencies live in an optional dependency group
3. A missing dependency or credential **disables** the provider with a clear message — it never crashes a build
4. Any feature set requesting its features fails validation *before* computation starts, naming the provider

Tested by `test_core_pipeline_runs_with_zero_providers_registered`.

---

## 4. Alignment strategies

Sparse, irregular records must become dense, bar-aligned features. How you do that is a modeling
decision, so it is explicit configuration rather than a hidden default.

| Strategy | Behavior | Use for |
|---|---|---|
| `last_known` | Carry the most recent available value forward | Fundamentals, ratings, positioning |
| `decay(half_life)` | Exponentially decay the value since publication | Sentiment, news impact |
| `window_agg(window, fn)` | Aggregate all records available within a trailing window | Headline counts, mean sentiment |
| `count(window)` | Number of records in a trailing window | News intensity, event clustering |
| `since_last(unit)` | Time elapsed since the last record | Event-proximity features |
| `impulse` | Non-null only on the bar where it became available | Scheduled releases |
| `scheduled_proximity` | Distance to the next known scheduled event | FOMC, NFP, earnings proximity |

All windows are **trailing**. A `window_agg` implementation that centers its window is a leakage bug,
and the property tests check for it.

### The as-of join

```python
def align(bars: pl.DataFrame, records: pl.DataFrame, spec: FeatureSpec) -> pl.Series:
    # Join on available_time, with strategy=backward: for each bar, the most recent
    # record whose available_time <= bar.ts. Never event_time.
    joined = bars.join_asof(
        records.sort("available_time"),
        left_on="ts", right_on="available_time",
        strategy="backward",
    )
    return spec.alignment.apply(joined)
```

One function, one rule, tested directly. `test_join_uses_available_time_not_event_time` is the single
most important test in this module — plant an `event_time` join and assert the suite catches it.

### Publication lag as a safety margin

Every provider declares `typical_publication_lag`, and feature sets may add an extra
`safety_lag` on top. When a vendor's `available_time` is unreliable — some backfilled datasets set it
equal to `event_time`, which is silently wrong — the safety lag is your defense. Default it
conservatively and document the choice.

**Rejection rule:** a record whose `available_time == event_time` for a source with a known nonzero
publication lag is rejected at ingestion with a named error. Backfilled data lying about availability
is a common and severe problem.

---

## 5. News & sentiment

### Data model

```python
class NewsRecord(PointInTimeRecord):
    payload: NewsPayload

class NewsPayload(BaseModel):
    headline: str
    body: str | None
    source: str
    symbols: list[str]              # resolved entities
    categories: list[str]           # "monetary_policy", "geopolitics", "supply"
    sentiment: SentimentScore | None
    relevance: float                # 0-1, symbol relevance
    novelty: float | None           # 0-1, is this new information or a rehash?
    url: str | None
    language: str

class SentimentScore(BaseModel):
    polarity: float                 # -1 to +1
    confidence: float               # 0-1
    model: str                      # which scorer produced this
    model_version: str
    scored_at: datetime             # affects available_time
```

### The scoring-time trap

If you score historical articles today with a model trained on 2026 data, the sentiment score's
`available_time` is **today**, not the publication date. Using it at a 2022 bar is leakage of both the
article and the model.

Two acceptable approaches:

1. **Live scoring going forward** — score at publication, `available_time = publication_time`. Clean,
   but only works for data collected from now on.
2. **Point-in-time-safe historical scoring** — use a model that could plausibly have existed at the
   time, or accept the score only as a *research* feature explicitly marked as not deployable.

Mark the distinction in the record: `scored_live: bool`. Feature sets used for validation runs may
require `scored_live == true`.

### Candidate features for gold

| Feature | Alignment | Rationale |
|---|---|---|
| `sentiment_polarity_ewm_60m` | `decay(60m)` | Decaying aggregate sentiment |
| `news_count_15m` | `count(15m)` | Intensity spike detection |
| `news_intensity_zscore_1d` | `window_agg(1d, zscore)` | Abnormal coverage vs baseline |
| `minutes_since_high_relevance_news` | `since_last(minutes)` | Post-event drift window |
| `minutes_to_next_fomc` | `scheduled_proximity` | Known-event proximity |
| `sentiment_dispersion_60m` | `window_agg(60m, std)` | Disagreement across sources |
| `macro_surprise_last` | `impulse` | Actual vs consensus on release |

For gold specifically, the categories that plausibly matter: monetary policy and real rates, dollar
strength, geopolitical risk, central bank buying, ETF flows, and physical supply/demand.

### Candidate sources
Free/cheap to start: RSS from major financial outlets, FRED for macro releases, CFTC COT reports,
central bank calendars. Paid, later: a proper news API with entity resolution and licensed sentiment.

**Recommendation:** build the framework and a `SyntheticNewsProvider` in Phase 6, and defer paying for
a news vendor until you have a technical-only baseline to measure against. Without a baseline you
cannot tell whether sentiment added anything.

---

## 6. Fundamentals (equities phase)

### Data model

```python
class FundamentalRecord(PointInTimeRecord):
    payload: FundamentalPayload

class FundamentalPayload(BaseModel):
    symbol: str
    period_end: date                # the fiscal period this describes
    fiscal_period: str              # "Q1-2026", "FY2025"
    report_date: date               # when filed  → drives available_time
    statement: Literal["income", "balance", "cashflow", "derived"]
    metrics: dict[str, float]
    currency: str
    is_restatement: bool
    restates_period: str | None
    filing_type: str                # "10-Q", "10-K", "8-K"
    source: str
```

### The three dates, and why all three are needed

`period_end` (what it describes) · `report_date` (when it was filed) · `available_time`
(when it became knowable, usually `report_date` plus filing-processing lag).

Backtests that join on `period_end` are using Q1 data throughout Q1 — before it existed. This single
mistake has produced more impressive-looking equity factor backtests than any other.

### Restatement handling

A restatement is a new record, never an overwrite:

```
Original:    period_end=2026-03-31, report_date=2026-04-28, revenue=1.20B, is_restatement=false
Restatement: period_end=2026-03-31, report_date=2026-11-12, revenue=1.05B, is_restatement=true,
             restates_period="Q1-2026"
```

At a bar in June 2026 the as-of join returns 1.20B — what the market believed then. From November
onward it returns 1.05B. Both are correct at their respective times, and the backtest reflects reality
instead of hindsight.

### Corporate actions
Splits and dividends adjust prices, not fundamentals. Keep the adjustment factors as their own
point-in-time series so historical per-share metrics can be reconstructed as-of any date.

### Candidate features
Valuation (P/E, EV/EBITDA, P/B) · growth (revenue and earnings YoY, sequential) · quality (ROE, ROIC,
margins, accruals) · leverage (net debt/EBITDA, interest coverage) · surprise (actual vs consensus,
post-earnings drift windows) · revision momentum (analyst estimate changes). Every one of them aligned
`last_known` on `available_time`.

---

## 7. Configuration

Feature sets are declarative, so the agentic layer can propose new ones as data rather than code.

```yaml
# configs/features/gold_with_sentiment.yaml
version: fs_v13
description: Baseline technical set plus decayed news sentiment

providers:
  - name: technical
    required: true
  - name: news_rss
    required: false            # set builds without it, features become null
    safety_lag: 60s
    config:
      sources: [reuters_metals, bloomberg_commodities]
      min_relevance: 0.6

features:
  - { provider: technical, name: volatility_atr_14, params: { period: 14 } }
  - { provider: technical, name: momentum_rsi_2,    params: { period: 2 } }
  - { provider: technical, name: regime_vol_quantile_60, params: { window: 60, buckets: 3 } }

  - provider: news_rss
    name: sentiment_polarity_ewm_60m
    alignment: { strategy: decay, half_life: 60m }
    null_policy: zero
    require_scored_live: true
  - provider: news_rss
    name: news_count_15m
    alignment: { strategy: count, window: 15m }
    null_policy: zero

validation:
  fail_on_missing_required_provider: true
  fail_on_unavailable_capability: true
  min_coverage_pct: 0.80        # reject the set if a feature is null in >20% of bars
```

`min_coverage_pct` matters for sparse sources: a sentiment feature that is null 95% of the time is not
a feature, it is noise with occasional structure, and a tree model will happily overfit it.

---

## 8. What the agent may do with providers

Within the agentic pipeline, providers expand the search space in a controlled way.

**Allowed:** propose new feature sets combining available providers · propose alignment strategies and
half-life parameters · propose relevance and category filters · request a comparison of a set with and
without a provider.

**Not allowed:** register new providers · alter `available_time` or lag parameters · disable
point-in-time validation · request features from a provider not configured for the campaign.

**Worth measuring explicitly:** every campaign that uses sentiment should run a matched
technical-only control. Reporting "with sentiment: Sharpe 1.4" is meaningless without "without
sentiment: Sharpe 1.35". Make the paired comparison a first-class campaign output, not something you
reconstruct by hand.

---

## 9. Testing requirements

```
tests/unit/test_provider_protocol.py
  test_provider_declares_capabilities
  test_core_pipeline_runs_with_zero_providers
  test_missing_dependency_disables_provider_cleanly
  test_missing_credential_disables_provider_cleanly
  test_feature_set_requesting_absent_provider_fails_before_computation

tests/unit/test_point_in_time.py
  test_available_time_never_precedes_event_time
  test_revision_creates_new_record_not_overwrite
  test_asof_returns_pre_revision_value_before_restatement_date
  test_asof_returns_revised_value_after_restatement_date
  test_backfilled_record_with_equal_times_rejected_for_lagged_source

tests/unit/test_alignment.py
  test_join_uses_available_time_not_event_time        # ★ the critical one
  test_last_known_carries_forward_without_leaking
  test_decay_weights_match_half_life
  test_window_agg_window_is_trailing_not_centered
  test_count_excludes_records_published_after_bar
  test_safety_lag_shifts_availability_forward
  test_sparse_records_do_not_forward_fill_past_null_policy

tests/property/test_alignment_invariants.py
  test_no_feature_value_at_t_changes_when_future_records_added   # ★ strongest guarantee

tests/leakage/test_provider_leakage.py
  test_planted_event_time_join_caught
  test_planted_restated_value_in_history_caught
  test_planted_future_scored_sentiment_caught
  test_planted_negative_lag_caught

tests/integration/test_synthetic_news_provider.py
  test_deterministic_events_produce_deterministic_features
  test_feature_set_with_and_without_provider_differ_only_in_provider_columns
```

**The property test is the strongest guarantee available here:** generate a set of records, compute
features up to time `t`, then append records with `available_time > t`, recompute, and assert every
feature value at or before `t` is unchanged. If that holds for arbitrary inputs, the join is sound.

---

## 10. Implementation order

| Step | Deliverable | Phase |
|---|---|---|
| 1 | `PointInTimeRecord`, three-timestamp contract, revision semantics | 6 |
| 2 | `FeatureProvider` protocol, capability declaration, registry | 6 |
| 3 | As-of join engine and all alignment strategies | 6 |
| 4 | `SyntheticNewsProvider` for deterministic testing | 6 |
| 5 | Wrap existing technical indicators as a `TechnicalProvider` | 6 |
| 6 | Full leakage and property test suites | 6 |
| 7 | Real news/sentiment provider (RSS + macro calendar) | Post-baseline |
| 8 | Paired with/without campaign comparison as a first-class output | With step 7 |
| 9 | Fundamentals provider with restatement handling | Equities phase |

**Step 5 matters more than it looks.** Wrapping the existing technical indicators in the same protocol
proves the abstraction is real. If technical features need a special path, the protocol is wrong, and
you will find that out now instead of when the sentiment provider arrives.

---

*The test for this architecture: adding a new external data source should require writing one adapter
class and one YAML block — no changes to the feature pipeline, the backtest engine, the validation
layer, or the UI. If a new source forces a change anywhere else, the abstraction has a hole in it.*
