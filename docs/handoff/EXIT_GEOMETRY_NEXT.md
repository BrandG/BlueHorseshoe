# Exit-Geometry / BUD Deploy — Session Handoff (2026-06-14)

**One-line restart:** The BUD exit-geometry work is **done and deployed**. The exit sweep found the
best per-trade exit by *total money* (TP 1.5% / SL 0.6% / 10-day; steadier alt TP 1.5% / SL 1.0% /
10-day), and the **steadier alt is wired LIVE** into the autonomous trader + briefing, scoped to the
long mean-reversion cells. Everything is committed on `master` (`c367ec1`, pushed). Next door is
to **watch the live long-MR trades vs the backtest** as trades mature.

> **UPDATE 2026-06-15:** Relative-value / cointegration (door #2, the one campaign door never tried)
> was opened and **CLOSED the next day**. P0 screen opened 15 pairs; P1 in-sample looked promising
> (+113R), but **P2 holdout FAILED (−61R OOS, 13/15 pairs flipped)** and dynamic-β confirmed the
> in-sample win was a static-β fitting artifact (~0 causal). That was the **last signal door of the
> campaign — all signal doors are now dead**; BUD edge = exits + execution + risk. Commits
> `fb7d7ab`/`d00b148`/`50373f0`. ([[project_relative_value_door]]) So §4 option 3 below is spent;
> the live remaining door is option 1.

---

## 1. What happened this session

1. **P4 — FTMO-constrained sim** (banked `60dd7a3`, `research/atr_regime_v1/atr_regime_p4_ftmo.py`).
   Audited off its own misleading "no deploy / pass-rate" headline: pass-rate is push-dominated
   (sizing/throughput proxy, not edge); the vol-regime filter is a **modest risk/dead-weight trim**,
   and `hard_gate` is constraint-optimal (reverses P3's `size_down` preference). Per-trade re-cut:
   win rate monotone in calm (low 53% / high 49%).

2. **Exit-geometry sweep** (banked `a11e05c` / merge `53d0cb4`, `research/exit_geometry_v1/`).
   Swept TP×SL×hold (6×5×4=120) on the deployed long-MR book, ranked by **total money** (sum of
   per-trade R), parameterized sim asserted == `_lib.py` at 1%/1%/14d (154,083 fires). Winner BOTH
   books: **TP 1.5% / SL 0.6% / 10-day** — strong-4 +1308R vs 1:1/14d baseline +1157R (+13%);
   full-6 +2085R vs +1745R (+20%); profitable in A/B + recent holdout. Pattern: **shorter hold
   (10 not 14d) + target wider than stop**. Win rate falls (34.7%) while money rises — total money,
   not win rate, is the scoreboard. A FTMO-account-drawdown framing was explored and **set aside**
   per Brand (per-trade question ≠ challenge-pass question).

3. **Deploy** (`c367ec1`, corrects `c4b50f7`). Wired the **steadier alt (TP 1.5% / SL 1.0% / 10-day)**
   into the **LIVE trader** + briefing, scoped to ONLY validated cells — long, MR (bb/rsi/ema/stoch),
   mid entry. Override baked into `briefing.compute_entry_stop_target` (keyed on cell) so the
   trader's entries AND the briefing/email agree; 10-day cap added to
   `auto_trader.close_aged_positions`. A live (non-dry) run closed the aged stoch/EUR_GBP long via
   the new 10-day cap.

## 2. Current git state
- `master` = `origin/master` = **`c367ec1`**, clean working tree, all pushed.
- No dangling branches/worktrees from this session (codex/atr-regime-p4 and codex/exit-geometry-v1
  merged + torn down). Parked worktrees `deepos-fill-anchored` / `solvency-deepos` are unrelated.

## 3. Critical gotchas — carry forward
- **The LIVE cron trader is `src/bud/auto_trader.py`** (`run_bh_ftmo_trader.sh`, :16), **NOT
  `auto_v2.py`** (legacy, unscheduled). Trace the cron before claiming any trader change is live —
  `auto_v2` is a decoy name. `run_bh_ftmo_v2_paper.sh` is not in crontab.
- **BUD per-trade-setup objective = TOTAL MONEY** (sum of R at constant risk), NOT win rate, NOT
  portfolio/account drawdown, NOT regime (calm/choppy) conditioning. Brand corrected this twice.
  ([[bud-eval-objective-total-pnl]])
- **Validation split** = interleaved calendar-quarter blocks (COVID in both halves) + last-24mo
  recent holdout; profit required in A AND B AND holdout. ([[bud-validation-split-interleaved]])
- **ASK before every git commit/push.** A prior "commit it" does NOT carry to the next change.
  ([[feedback-ask-before-every-commit]])

## 4. Immediate next options (pick one next session)
1. **Watch the live long-MR trades vs the backtest.** The deployed exits project ~+14% more total
   money on the strong-4 book; the reconciler (`src/bud/reconcile.py` → `bh_ftmo_outcomes.csv`)
   joins OANDA closes → placements. First matured long-MR trades land in ~weeks; compare live-R to
   the sweep.
2. **The aggressive winner (TP 1.5% / SL 0.6% / 10-day)** — most total money (+13%/+20%) but a
   tighter 0.6% stop and uneven across eras on strong-4. **Parked**; deploy only if Brand wants more
   aggression after seeing the steadier alt run.
3. ~~**Relative-value / cointegration (door #2)** — untouched the entire campaign; the orthogonal
   unopened door now that confluence/depth are dead and vol-regime + exits are mined.~~
   **CLOSED 2026-06-15** — P0 opened (15 pairs), P1 in-sample promising (+113R), P2 holdout FAILED
   (−61R OOS, 13/15 flipped), dynamic-β confirmed static-β fitting artifact. Last signal door of the
   campaign; all signal doors now dead. Commits `fb7d7ab`/`d00b148`/`50373f0`.
   ([[project_relative_value_door]])

## 5. Memory pointers
- `project_confluence_closed_dislocation_depth.md` — full campaign rollup (confluence→depth→
  vol-regime→P4→exit sweep→deploy), with the deploy details + the auto_trader-not-auto_v2 note.
- `bud_eval_objective_total_pnl.md`, `bud_validation_split_interleaved.md`,
  `feedback_ask_before_every_commit.md` — the method/process steers from this session.
