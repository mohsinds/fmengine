# /leak-audit

Audit the selected code (or the whole feature/backtest path) for look-ahead bias and data leakage.
Run this before trusting *any* promising backtest result.

## Checklist — go through every item explicitly, state pass/fail/NA with evidence

### Temporal leakage
- [ ] Does any feature at bar `t` read data from `t+1` or later?
- [ ] Are rolling windows strictly trailing? (`center=True` anywhere = fail)
- [ ] Is the bar timestamp convention (bar-open) applied consistently?
- [ ] Is a close-derived signal acted on at the *next* bar, not the same bar's close?
- [ ] Are fills priced at next-bar open or with explicit intrabar modeling — never signal-bar close?
- [ ] Do stop/target checks respect intrabar path ambiguity (which of high/low hit first)?

### Fit leakage
- [ ] Are scalers/encoders/imputers fit on training folds only, never on the full series?
- [ ] Is CV purged and embargoed around label windows?
- [ ] Are overlapping labels down-weighted via sample uniqueness?
- [ ] Was any hyperparameter chosen using data that also produced the reported metric?

### Survivorship / construction
- [ ] Continuous-contract adjustment applied without leaking future roll info?
- [ ] Any symbol filtering that implicitly uses future knowledge?

### External data (if present)
- [ ] News/sentiment aligned by **publication** time with an explicit lag?
- [ ] Fundamentals point-in-time as-reported, not restated?

### Holdout hygiene
- [ ] Did this code path touch the holdout vault? Was a token used and logged?
- [ ] Was the config tuned on data overlapping the reported evaluation window?

## Output
For each failure: the exact file and line, why it leaks, and the fix. Then state your overall verdict:
`CLEAN` / `SUSPECT` / `LEAKING`. If `LEAKING`, all downstream results are invalid — say so directly.
