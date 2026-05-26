# Contrarian / Entry-Distance Thread — Next Steps

**Created:** 2026-05-22
**Originating session:** `9a48c5c7-fb77-4623-8bcd-20611dd14520` (resume with `claude --resume <id>`)
**Reminder fires:** 2026-05-29 13:00 UTC (09:00 ET, Friday)

## What just happened (2026-05-22 session)

Five-addendum study of the BH baseline strategy under limit-entry execution. Full doc: `docs/results/CONTRARIAN_SHORT_v1_RESULTS.md`. Memory: `~/.claude/projects/-root-BlueHorseshoe/memory/project_contrarian_short_v1.md`.

Commits this session (on top of `14417c0`):

```
382fb91 fix(ibkr): entry leg uses DAY tif, not GTC — unfilled limits die at EOD
129553a docs(research): addendum 5 — provenance audit + ENTRY_DISCOUNT_BY_SIGNAL is the lever
46ac902 results(research): addendum 4 — entry-distance has the entire edge, score has zero residual
4cc7349 results(research): addendum 3 — RR-cell sweep (inverted-score structural, 6/6 cells)
5d107f6 results(research): addendum 2 — score ranking inverts under limit-entry
e092d6d results(research): addendum — limit-at-entry_price adds +0.28pp/trade
4e25915 chore: subsystems guide + ftmo symbol auto-suffix + ignore IBKR journal
aab7e18 results(research): CONTRARIAN_SHORT_v1 — top-10 baseline @ next-day-open significantly negative
```

## Key findings (compressed)

1. **Limit-at-`entry_price` mechanic is load-bearing for production edge** (~+0.28 pp/trade vs market-buy at next-day open).
2. **Score ranking inverts under limit-entry**, but only because of the constants table:
   - `ENTRY_DISCOUNT_BY_SIGNAL` in `src/bluehorseshoe/analysis/constants.py:75` hard-codes EXTREME→0.05 ATR, WEAK→0.50 ATR.
   - Wide entry-distance (low score, high ATR discount) produces ~3.4× per-trade R vs narrow (Q1 +0.090% → Q5 +0.618%).
   - Cross-tab proved: entry-distance has all the edge; score has zero residual.
3. **Provenance verified** — no look-ahead. `entry_price = close_on_score_date − atr_discount × atr`. Result is real.
4. **TIF=DAY for the entry leg shipped** in `382fb91`. TP/SL remain GTC. Aligns the automated path with how Brand executes manually.

## What to gather before resuming

**Original plan:** by 2026-05-29 we'd have ~4 trading days of post-Memorial-Day DAY-tif live data (Tue/Wed/Thu/Fri).

**Revised plan after the 2026-05-26 bellwether incident** (see "Incident log" below): expect at most **3 trading days** of clean end-to-end data by Friday — Wed 27, Thu 28, Fri 29. **Tuesday's pipeline did not run successfully.** And as of 2026-05-26 02:55 UTC, MongoDB shows **only 1 of 248,927 baseline scores has `actual_close` populated**, even though the code change shipped Friday — strongly suggesting Saturday's `-p` either didn't write the field, or `ScoreManager.save_scores` upserts on `(symbol, date)` without overwriting the metadata block. Investigate before trusting any fill-rate-by-tier analysis.

- Two weeks would still be better (~9 trading days, Friday 2026-06-05). Given the incident burned one day, pushing the cron to 06-05 is the more conservative call.

**Data to pull before resuming:**

1. **Fill rate by signal-strength tier.** Query `trade_orders` + IBKR executions for the 5-day window. Group by the tier the prediction landed in (EXTREME/HIGH/MEDIUM/LOW/WEAK — derive from score, since the tier itself isn't stored). Compute: submissions per tier, fills per tier, fill-rate per tier.
   - **Expected pattern if the simulator is right:** EXTREME ~71%, MEDIUM ~60%, WEAK ~48% (mirror of the Q1→Q5 gradient).
   - **If actual fill rates diverge from this**, that's the first data point that should reshape our thinking.

2. **Per-tier per-trade R for filled positions.** Of the trades that DID fill, what was the mean R per tier? With only 4 trading days you'll get tiny samples (< 50 fills total), so this is directional only — don't over-interpret.

3. **Any orphan orders.** Confirm IBKR auto-cancelled child legs (TP/SL) when their parent DAY entries expired unfilled. Quick check: `get_open_trades()` shouldn't show any SELL legs without a matching position or active entry.

4. **Mongo audit-trail health.** How many `trade_orders` rows are sitting at `status: "submitted"` with no broker presence? This is the audit gap I flagged in commit `382fb91`. If it's growing, prioritize the `cancelled_no_fill` sweep enhancement.

## Suggested first prompt on resume

> Resuming the contrarian_short_v1 / entry-distance thread. Read `docs/handoff/CONTRARIAN_NEXT.md`. I've gathered fill-rate data for the [date range] DAY-tif window. Let's look at whether the actual fill-rate pattern per tier matches the simulator's prediction, and decide whether `ENTRY_DISCOUNT_BY_SIGNAL` needs retuning.

## Open follow-ups (don't lose these)

- **Volatility confound.** `entry_dist_pct = atr_discount × atr / close`. Q5 might be partly "trade volatile names" rather than "trade wider pullback." Needs within-volatility-quintile decomposition.
- **Longer-window replication.** Requires backfilling `trade_scores` (currently only goes back to 2026-02-12).
- **ENTRY_DISCOUNT_BY_SIGNAL retuning.** Three options in the results doc (invert / flatten / rank post-hoc). Pick once live data arrives.
- **Mongo audit-trail sweep.** Flip stale `status: "submitted"` rows to `cancelled_no_fill` when broker doesn't see them and position is zero.

## Operational checks before any prod change

- Verify the `382fb91` change is actually deployed (the systemd service may need a restart to pick up new code).
- Verify cron timezone — if you re-run -p outside US hours, the IBKR session-close auto-cancel still happens correctly.
- Sanity-check `_get_occupied_symbols` returns expected counts each morning (no zombies).

## Incident log

### 2026-05-26: Memorial Day → bellwether retry loop, no email Tuesday

**Symptom:** Brand noticed no daily report email for several days. Last legitimate email was Saturday 2026-05-23 (for Fri 2026-05-22 data).

**Root cause:** `check_market_status` in `bluehorseshoe/data/historical_data.py` adjusted for Sat/Sun but had **no US market holiday awareness**. Memorial Day 2026-05-25 (Mon) was the first holiday after the cron `0 1 * * 2-6` schedule put Tue at the head of the run sequence. On Tue 01:00 UTC the bellwether expected Mon SPY data from Tiingo, never got it (market closed), looped at 01:00 and 02:00 UTC. The 3 AM abort in `main.py:104` would have fired at 03:00 and exited cleanly without a report.

**Timeline (all UTC):**
- 2026-05-26 01:00 — cron fires, `-u --active-only` enters bellwether retry loop.
- 02:00 — retry, same failure.
- ~02:40 — Brand asks "why no email", session investigates.
- ~02:45 — diagnosis confirmed (`Bellwether check failed: Expected 2026-05-25, found 2026-05-22` in `daily_pipeline.log`).
- ~02:45 — PID 684578 (`src/main.py -u --active-only`) killed via SIGTERM, exited cleanly.
- ~02:44 — manual recovery: `./run.sh python src/main.py -r 2026-05-22` regenerated Friday's report; `./run.sh python src/send_report_email.py` emailed it via Brevo. Brand received a "duplicate" Friday report so the daily cadence didn't visibly skip a day.
- ~02:55 — durable fix shipped as commit `c0b88b6`: `check_market_status` now walks `expected_date` back through both weekends AND NYSE holidays (reusing the existing `core/market_calendar.nyse_holidays_for_year`). Three regression tests added.

**Open question raised by the investigation:** MongoDB has 1 score with `metadata.actual_close` populated, out of 248,927 baseline scores total. The `actual_close` field was added in commit `fd8e07b` (pushed Friday 2026-05-22 before the Saturday cron). Saturday's `-p` should have written the field on the 2026-05-22 scores it regenerated, but didn't. Two leading hypotheses:
1. `ScoreManager.save_scores` upserts on `(symbol, date, strategy)` and preserves the existing metadata block instead of overwriting. Worth code-reading `core/scores.py`.
2. Saturday's `-p` actually short-circuited (skipped writing because scores already existed for that date) — different from option 1 in that scores weren't touched at all.

Either way, **the entry-distance column will only start populating from Wednesday's cron forward**, on fresh score dates that have no prior trade_scores rows to upsert against. If the column is empty in Thursday's email too, that's confirmation that the save-scores path needs a fix.

**Lesson:** the cron `2-6` schedule means any Monday holiday becomes a Tuesday silent failure unless the bellwether is holiday-aware. Memorial Day, MLK Day, Presidents' Day, Labor Day, and Columbus/Indigenous Peoples' Day all fall on Mondays. With `c0b88b6` shipped, these are all covered going forward.
