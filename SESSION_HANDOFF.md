# Session Handoff

> **Research reset 2026-06-25.** The prior handoff (GORDON/BUD research findings — S/R,
> indicator teardown, contrarian, BUD H4 edges, etc.) was cleared along with the `research/`
> tree and its memory, so research can be regenerated cleanly under the current testing
> standards. Operational state below; research findings start fresh.

## Live / operational state

**GORDON (US equities / IBKR)**
- Engine (`bluehorseshoe/` + `main.py`): daily `-u` update + `-p` prediction pipeline on cron.
- Manager (`bh_swing/`): post-fill stop management, LIVE (`--manage`, BREAKEVEN moves) on paper acct.
- Data pulls that regenerate `data/*.parquet` now live in `src/bluehorseshoe/maintenance/data_pulls/`.

**BUD (forex / FTMO / OANDA)**
- Briefing (`src/bud/briefing.py` + `briefing_ftmo.py`): human-in-loop, emailed FTMO briefing on cron.
- Auto (`src/bud/auto_trader.py`): autonomous unified trader (V2 cells) on OANDA practice.

## Operational incident log (preserved)

### 2026-05-26 Memorial Day silent failure
`check_market_status` in `bluehorseshoe/data/historical_data.py` had no US-holiday awareness.
Memorial Day (Mon) → Tue cron expected Mon SPY data, never got it, looped, aborted at 3 AM without a
report. **Durable fix `c0b88b6`:** `check_market_status` now walks `expected_date` back through
weekends AND NYSE holidays (reusing `core/market_calendar.nyse_holidays_for_year`); 3 regression tests
added. Lesson: the cron `2-6` schedule makes any Monday holiday a Tuesday silent failure unless the
bellwether is holiday-aware — now covered.
