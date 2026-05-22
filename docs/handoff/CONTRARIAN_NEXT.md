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

By 2026-05-29 we'll have ~4 trading days of post-Memorial-Day DAY-tif live data:

- Trading days expected: Tue 2026-05-26, Wed 27, Thu 28, Fri 29.
- Two weeks would be better (~9 trading days, Friday 2026-06-05). If you'd rather wait, push the cron back.

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
