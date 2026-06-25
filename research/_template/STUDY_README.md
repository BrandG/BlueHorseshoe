# <STUDY_NAME>_v1

> Copy this directory to `research/<study_name>_v1/` to start a study. Keep this file current —
> it is the session handoff. Start every session by re-reading it.

## Product
GORDON (long-only equity)  /  BUD (forex H4)   ← pick one; it sets the eval bar (README §0).

## Question
One sentence. What edge / setup / exit are we testing, and what would make it real?

## Hypothesis
What we expect and why. Name the mechanism, not just the pattern.

## Method (harness used)
- Outcome: bracketed R, worst −1R, target_R=__, max_hold=__  (via `_lib.bracket_trade`)
- Filters: vol floor atr_pct≥0.005, $vol floor ($1M screen / $25M liquid), split/delist guard = __
- Stats: all firings kept; Newey-West L=hold−1 + symbol-clustered SE (via `_lib.summarize_R`)
- Canary: matched random benchmark reads ____R (must be ~0.000)
- Temporal: per-calendar-year read (NOT a 2-bin split)
- OOS (deploy only): interleaved A/B + last-24mo holdout
- Layer 3 (deploy only): next-open fills + tiered cost stress

## Runners
- `____.py` — what it does (prints its own ledger)

## Data
Inputs from `data/*.parquet` (regenerate via `src/bluehorseshoe/maintenance/data_pulls/`) and the
DuckDB OHLCV store. Nothing canonical lives in this directory.

## Status
OPEN / null / validated. What ran, what's left, what's blocked.

## Result / Verdict
The honest number(s) with SE + t. RAW-vs-CLEANED delta. Frame a null as a closed door + the next
door, never an obituary (README §3). Audit the harness before writing "dead".

## Checklist (README §5)
- [ ] bracketed R, not raw forward returns
- [ ] vol + $vol floors (tier stated)
- [ ] split/delist guard
- [ ] all firings kept; NW + clustered SE
- [ ] random benchmark ~0.000R
- [ ] per-year temporal read
- [ ] (deploy) next-open + cost stress
- [ ] (deploy) profitable in A AND B AND holdout
- [ ] RAW-vs-CLEANED delta shown
- [ ] verdict = door, not obituary
