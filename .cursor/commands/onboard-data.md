# /onboard-data

Add a new vendor, instrument, or asset class without touching core code.

**Usage:** `/onboard-data databento GC futures` · `/onboard-data ccxt BTC-USD` · `/onboard-data polygon AAPL`

## Steps
1. **Capability audit first.** Document what the vendor provides: volume? spread/quotes? open interest?
   depth? session calendar? corporate actions? point-in-time fundamentals? Revision policy?
2. Write `data/adapters/<vendor>.py` implementing the adapter interface. Normalization only — no
   indicator logic, no opinionated cleaning beyond documented and logged steps.
3. Declare capabilities in the adapter so the feature pipeline can gate features correctly.
4. **Futures:** implement the roll rule and continuous-series method for this instrument. Document the
   choice (back-adjusted/Panama vs ratio vs unadjusted) and its implications for indicator computation
   and for return calculation. Keep raw per-contract data alongside the continuous series — you cannot
   actually trade a continuous contract.
5. **Equities:** point-in-time fundamentals only, as-reported. Handle splits/dividends explicitly.
6. **Crypto:** 24/7 calendar, no roll, funding rates for perps.
7. Extend the session calendar registry.
8. Run the quality gate; commit the snapshot manifest.
9. Add integration tests: schema conformance, timezone correctness, gap classification against the
   real calendar, and a round-trip write/read equality check.

## Report
Capability table, row counts, coverage by month, quality findings, and an explicit list of which
existing features and strategies become newly available or newly unavailable with this dataset.
