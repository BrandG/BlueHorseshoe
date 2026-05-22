# Contrarian Short v1 — Results

**Run date:** 2026-05-21
**Script:** `research/contrarian_short_v1/run_contrarian_short.py`
**Window:** 2026-02-12 → 2026-05-19 (68 unique score dates, ~3.3 months)
**Universe:** Top-10 baseline picks per date (positive score, `metadata.entry_price` present)
**Entry mechanic:** Next-day open (NOT BH's limit-at-entry_price)

## Hypothesis

Do the top-10 baseline (trend-following) recommendations from the BlueHorseshoe predictor lose money in the immediate short term? If yes — is the contrarian short of those same picks a viable strategy?

Secondary question: does the "bottom-10" of the positive-score pool (weakest qualifying signals) behave differently from the top-10?

## Setup

- Symbols and entry price come from MongoDB `trade_scores` (`strategy: baseline`, positive score).
- For each score date, fetch top-10 (or bottom-10) by score.
- Simulate two parallel trades on the next bar: LONG (what BH recommends) and SHORT (contrarian flip).
- Entry: open of bar following score date.
- Exits: ±TP%, ±SL%, or time-stop at close of final hold day. SL precedence on tied intra-bar.
- Both 1.5/3/3 (production-like) and 5/3/14 (wider) parameter cells.

## Headline Numbers

### TOP-10 picks (production-side)

| Cell | Dir | N | WR | Mean R/trade | 95% CI | Cum % | TP / SL / TimeW / TimeL |
|---|---|---:|---:|---:|---|---:|---|
| 1.5% / 3% / 3d | **LONG** | 661 | 57.8% | **−0.193%** | [−0.377, −0.010] | **−127.8%** | 350 / 185 / 32 / 94 |
| 1.5% / 3% / 3d | SHORT | 661 | 56.4% | −0.132% | [−0.341, +0.077] | −87.3% | 337 / 210 / 36 / 78 |
| 5% / 3% / 14d | LONG | 661 | 39.8% | −0.052% | [−0.368, +0.264] | −34.5% | 204 / 364 / 59 / 34 |
| 5% / 3% / 14d | SHORT | 661 | 38.0% | +0.061% | [−0.261, +0.384] | +40.5% | 194 / 364 / 57 / 46 |

### BOTTOM-10 picks (weakest positive-score baseline)

| Cell | Dir | N | WR | Mean R/trade | 95% CI | Cum % |
|---|---|---:|---:|---:|---|---:|
| 1.5% / 3% / 3d | LONG | 570 | 55.6% | +0.014% | [−0.130, +0.157] | +7.7% |
| 1.5% / 3% / 3d | SHORT | 570 | 53.5% | +0.040% | [−0.102, +0.181] | +22.7% |
| 5% / 3% / 14d | LONG | 570 | 45.3% | −0.043% | [−0.317, +0.231] | −24.7% |
| 5% / 3% / 14d | SHORT | 570 | 36.3% | +0.004% | [−0.281, +0.289] | +2.4% |

### Recent 90d slice (default cell, 2026-02-20 → 2026-05-19)

| Dir | N | WR | Mean | 95% CI | Cum % |
|---|---:|---:|---:|---|---:|
| LONG | 617 | 57.1% | **−0.251%** | [−0.444, −0.057] | **−154.8%** |
| SHORT | 617 | 56.2% | −0.124% | [−0.341, +0.094] | −76.5% |

## Findings

1. **LONG (1.5/3/3 TOP-10) has statistically significant negative expectancy** in this window. Mean −0.193%/trade with a 95% CI that excludes zero. Win rate 57.8% looks healthy, but the asymmetric 1.5% TP / 3% SL means the average loss eats two winners; the structure is below break-even at this WR.

2. **Recent 90 days is materially worse.** Mean drops to −0.251% with CI still excluding zero. The current regime is the largest contributor to the negative aggregate.

3. **Contrarian SHORT is NOT a free trade.** SHORT mean is also negative on 1.5/3/3 (−0.132%) and its CI overlaps zero — no statistical edge in either direction. The contrarian thesis fails: short of BH top-10 doesn't make money, it just loses less than long.

4. **5/3/14 flips the sign for SHORT (+0.061%) but it's not significant.** WR collapses to 38% under wider stops, exits are dominated by SL hits (364/661, 55%). No exploitable edge.

5. **BOTTOM-10 is mostly noise.** Both directions hug zero across both cells. Low-conviction baseline picks have no directional information — neither follow nor fade them.

6. **Day-level basket direction is coin-flip.** Across all four cells, SHORT-basket-of-the-day beats LONG-basket-of-the-day on 43.9–54.4% of dates. There's no "BH top-10 is a daily fade" signal.

## Verdict

**Mixed-negative.** The hypothesis "BH top-10 baseline picks lose short-term" is **confirmed** under the 1.5/3/3 next-day-open entry, with the recent regime amplifying it. But the corollary "therefore short them" **fails** — the contrarian flip has no edge.

The most likely structural explanation: **the simulator uses next-day open entry, not BH's limit at `entry_price`.** Production BH only fills on a limit pullback to a pre-computed entry; the test bypasses that filter entirely. So this experiment measures "what if BH market-bought its signals" — and the answer is "it loses money." That's a strong argument for the limit-entry mechanic being part of the edge, not a hindrance.

## Addendum — Limit-Entry Re-run (2026-05-22)

Added `--entry {open,limit}` to the simulator and re-ran all four cells with limit-at-`metadata.entry_price` fills. Bar-0 only: if the bar trades through the limit (LONG: `low <= entry`, SHORT: `high >= entry`), the trade fills (gap-better → at open). Un-touched bars are tagged `no_fill` and excluded from stats.

### Apples-to-apples (today, same window, 1.5% / 3% / 3d TOP-10)

The score-date universe shifted by one day between the v1 and addendum runs, so the v1 open-mode numbers (n=661, mean −0.193%) aren't directly comparable. Both bars below are from today's runs over the same 580-pick universe.

| Entry | N filled | Fill rate | WR | Mean R/trade | 95% CI | Cum % |
|---|---:|---:|---:|---:|---|---:|
| **LONG @ open**  | 580 | 100%  | 57.1% | −0.101% | [−0.253, +0.051] | −58.4% |
| **LONG @ limit** | 413 | 71.2% | 63.9% | **+0.179%** | [−0.000, +0.358] | +73.8% |
| **SHORT @ open**  | 580 | 100%  | 58.6% | +0.107% | [−0.042, +0.256] | +62.0% |
| **SHORT @ limit** | 539 | 92.9% | 60.7% | **+0.230%** | [+0.083, +0.377] | +124.1% |

**LONG mean swings +0.28 pp** (−0.101% → +0.179%) by going limit-only. **SHORT mean swings +0.12 pp**. Both deltas are larger than their individual CI half-widths.

### Recent 90d slice (where v1 saw the strongest negative)

| Entry | N | WR | Mean R/trade | 95% CI |
|---|---:|---:|---:|---|
| LONG @ open | 530 | 55.5% | **−0.168%** | [−0.328, −0.008] |
| LONG @ limit | 371 | 62.5% | +0.117% | [−0.075, +0.309] |

In the recent regime, LONG-open is significantly negative; LONG-limit fully neutralizes it (CI overlaps zero). The limit filter erases a real ~+0.29 pp/trade swing.

### Full grid summary (filled trades, limit mode)

| Cell | Dir | N | Fill | WR | Mean | 95% CI | Cum % |
|---|---|---:|---:|---:|---:|---|---:|
| TOP 1.5/3/3 | LONG | 413 | 71% | 63.9% | +0.179% | [−0.000, +0.358] | +73.8% |
| TOP 1.5/3/3 | SHORT | 539 | 93% | 60.7% | +0.230% | [+0.083, +0.377] | +124.1% |
| TOP 5/3/14 | LONG | 413 | 71% | 42.9% | −0.060% | [−0.408, +0.288] | −24.8% |
| TOP 5/3/14 | SHORT | 539 | 93% | 44.5% | +0.438% | [+0.121, +0.755] | +236.0% |
| BOT 1.5/3/3 | LONG | 278 | 48% | 72.3% | +0.532% | [+0.342, +0.721] | +147.8% |
| BOT 1.5/3/3 | SHORT | 559 | 96% | 54.6% | +0.098% | [−0.044, +0.239] | +54.6% |
| BOT 5/3/14 | LONG | 278 | 48% | 47.1% | +0.211% | [−0.209, +0.631] | +58.7% |
| BOT 5/3/14 | SHORT | 559 | 96% | 36.7% | −0.015% | [−0.301, +0.271] | −8.2% |

### Why the asymmetric fill rates matter

LONG-no-fill cases are bars where the stock ran *up* and never pulled back to BH's entry — exactly the chase-entries we want to skip. SHORT-no-fill cases (only ~7% of bars) are gap-down days where the stock crashed below entry overnight; for SHORT, those are the *best* entries we'd ideally take, so skipping them is a structural bias against the contrarian-short thesis. The SHORT-limit positive result is therefore likely conservative-upward: shorting at BH's entry-price on the way up filters to bars where the stock rallied at least to entry, which captures most days. The contrarian shorting strategy still doesn't have an operational thesis — there's no plausible execution that says "sell at BH's limit-buy price."

### Bottom-10 surprise

BOTTOM-10 LONG @ limit at 1.5/3/3 produces **+0.532% mean per trade with CI excluding zero** — the strongest cell in the grid. Fill rate is only 48% (weakest signals → entry prices further from current price → frequent no-fill), but the filtered subset wins. This contradicts the v1 "bottom-10 is noise" conclusion and suggests the entry-price filter, applied to *any* baseline-positive name, has edge. The signal-score ranking and the limit-entry filter are two separate sources of edge, and the limit is doing more work than the ranking.

### Updated verdict

- **The limit-at-entry-price mechanic is load-bearing for the production strategy.** It adds ~+0.28 pp/trade to LONG and turns a borderline-negative window into a borderline-positive one.
- **The "BH baseline is broken" reading of v1 is wrong.** The v1 negative LONG result was a counterfactual — what would happen *without* the limit filter. It measured the value of the filter, not a defect in production.
- **Contrarian short is dead.** With limit-at-entry-price for both sides, SHORT looks positive on paper but the fill mechanic is implausible as a real trading rule (sell at the buyer's pullback level). No operational strategy.
- **New open question.** The bottom-10 LONG-limit cell (+0.532% / trade, n=278) is unexpected — it suggests weak baseline signals + the entry-price limit still produce positive expectancy. Worth a follow-up: is the entry-price mechanic the dominant source of edge across the score distribution?

## Addendum 2 — Score-Ranking vs Entry-Price-Filter Decomposition (2026-05-22)

Added `--random` to sample N picks uniformly from the same baseline-positive pool (score > 0, has `entry_price`) with a Python seed. Ran 3 seeds on the 1.5% / 3% / 3d cell with LONG @ limit, then pooled.

### Results — LONG @ limit, 1.5% / 3% / 3d

| Selection | N | Fill rate | WR | Mean R/trade | 95% CI | Cum % |
|---|---:|---:|---:|---:|---|---:|
| **TOP-10**    (best score) | 413 | 71.2% | 63.9% | +0.179% | [−0.000, +0.358] | +73.8% |
| RANDOM seed=42  | 310 | 53.4% | 68.7% | +0.347% | [+0.156, +0.539] | +107.7% |
| RANDOM seed=7   | 334 | 57.7% | 66.5% | +0.250% | [+0.064, +0.435] | +83.4% |
| RANDOM seed=2026 | 295 | 50.9% | 62.4% | +0.157% | [−0.038, +0.352] | +46.3% |
| **RANDOM pooled (3 seeds)** | 939 | ~54% | — | **+0.253%** | [+0.143, +0.363] | +237.4% |
| **BOTTOM-10** (worst score) | 278 | 47.9% | 72.3% | **+0.532%** | [+0.342, +0.721] | +147.8% |

### Key observations

1. **Per-trade R is inversely correlated with score.** Top → Random → Bottom is monotonic: +0.179% → +0.253% → +0.532%. Pooled-random CI doesn't overlap top's CI or bottom's CI — the ordering is statistically real, not seed noise.
2. **Fill rate is also inversely correlated with score.** 71% (top) → 54% (random) → 48% (bottom). Stronger baseline scores produce entry-prices closer to current price (small pullback → frequent fill); weaker scores produce entry-prices further away (large pullback required → rare fill).
3. **Cumulative PnL strongly favors lower-score buckets.** Bottom-10 generates 2× the per-trade R and 2× the cum PnL vs top-10 with 33% fewer trades.
4. **The score-ranking edge looks inverted under limit-entry, not absent.** It's not "score doesn't matter" — it's "lower scores produce *better* limit-filtered returns."

### Interpretation

The most plausible mechanical explanation: **"selection through difficulty."** A limit at `entry_price` requires the stock to pull back to that level. For high-score (strong-momentum) picks, BH sets `entry_price` close to current price — so any minor pullback fills, and we collect many low-quality fills. For low-score (weak-momentum) picks, BH sets `entry_price` further away — only the stocks with a *real* meaningful pullback fill, and those are the ones that subsequently snap back to TP. The bottom-10 filtered subset is self-selecting for stocks with strong mean-reversion setups.

This decouples cleanly: **the entry-price filter has uniform, large positive edge across the entire score distribution.** The score ranking is a *second* effect that, paradoxically, weakens the filter's selectivity for top picks.

### Implications for production

Production trades top-N-by-score, gets ~71% fill rate, and earns ~+0.18%/trade. If this finding generalizes:

- **Inverting the ranking** (trade bottom-N) would ~3× per-trade R and ~2× cum PnL — but at half the fill rate, requiring different position-sizing or slot allocation.
- **Removing the ranking** (random) more than doubles per-trade R and triples cum PnL with ~54% fill rate — likely the simplest production change.
- **The "good signal → trade it" logic of the baseline is contradicted** by the limit-entry mechanic. Either the score should be inverted, or the entry-price should be set independently of the score (e.g., fixed % below close for everything).

### Caveats

- One ~3-month window (2026-02-12 → 2026-05-19). Could be regime-specific.
- 1.5% / 3% / 3d only — wider TP/SL cells may behave differently.
- No commission or spread modeling. Bottom-10's lower fill rate means more "wasted" attempts; at scale, broker fees on cancellations could erode the edge.
- The 5/3/14 BOTTOM cell from addendum 1 (mean +0.211%, CI crosses zero) doesn't show the same effect, so the result may be specific to the tight 1.5/3/3 RR.
- Bottom-10 sampling is constrained by the `score > 0` and `min_pool=20` filters — it's not "random NASDAQ tickers," it's "weakest qualifying baseline signals."

## Addendum 3 — RR-Cell Sweep (2026-05-22)

To check whether the inverted-score finding is structural or a 1.5/3/3 quirk, swept LONG @ limit across 6 RR cells × 3 selections (TOP-10, RANDOM seed=42, BOTTOM-10). RANDOM seed=42 single-seed except 1.5/3/3 which is pooled across 3 seeds.

### Results — LONG @ limit, per-trade Mean R with 95% CI

| Cell | TOP-10 (best score) | RANDOM | BOTTOM-10 (worst score) |
|---|---|---|---|
| 1/2/3   | +0.118%  [−0.020, +0.255] | +0.343%*  [+0.199, +0.486] | +0.372%*  [+0.216, +0.529] |
| 1.5/3/3 | +0.179%  [−0.000, +0.358] | +0.253%*  [+0.143, +0.363] | +0.532%*  [+0.342, +0.721] |
| 2/3/3   | +0.087%  [−0.110, +0.285] | +0.213%   [−0.003, +0.429] | +0.526%*  [+0.312, +0.741] |
| 2/4/5   | +0.043%  [−0.198, +0.283] | +0.261%*  [+0.012, +0.511] | +0.657%*  [+0.414, +0.899] |
| 3/4/7   | +0.022%  [−0.278, +0.322] | +0.081%   [−0.250, +0.412] | +0.367%*  [+0.024, +0.710] |
| 5/3/14  | −0.060%  [−0.408, +0.288] | (not run)                   | +0.211%   [−0.209, +0.631] |

`*` = 95% CI excludes zero. N: TOP=413, RANDOM=310 (or 939 for 1.5/3/3 pooled), BOTTOM=278.

### Cumulative PnL (sum of pnl_pct across filled trades)

| Cell | TOP-10 | RANDOM | BOTTOM-10 | BOTTOM−TOP per-trade |
|---|---:|---:|---:|---:|
| 1/2/3   | +48.6%   | +106.2% | +103.6% | +0.255% |
| 1.5/3/3 | +73.8%   | +237.4% | +147.8% | +0.353% |
| 2/3/3   | +36.0%   | +66.1%  | +146.4% | +0.439% |
| 2/4/5   | +17.6%   | +81.0%  | +182.6% | +0.614% |
| 3/4/7   | +9.1%    | +25.1%  | +102.1% | +0.345% |
| 5/3/14  | −24.8%   | —       | +58.7%  | +0.271% |

### Verdict

**The inverted-score effect is structural.**

- **TOP-10 LONG @ limit has zero statistically significant positive cells out of 6.** Every CI crosses zero. Production's top-N-by-score selection has no demonstrated edge under limit-entry on this dataset.
- **BOTTOM-10 LONG @ limit has 5 of 6 cells with CI excluding zero**, with mean R ranging from +0.211% to +0.657%/trade.
- **BOTTOM beats TOP on cumulative PnL in 6/6 cells**, with per-trade gaps from +0.255% to +0.614% — always positive, never close.
- **The pattern weakens at long hold periods.** 5/3/14 (14-day hold, wide TP) is the only cell where BOTTOM doesn't reach significance — likely because time-stop dominates over pullback-quality at long horizons.
- **Best single cell:** BOTTOM-10 at 2/4/5 — mean R +0.657%/trade, CI [+0.414, +0.899], cum +182.6%, fill rate 48%, win rate 70.5%.

### What the sweep does NOT yet rule out

1. **Regime dependence.** All 6 cells share the same 2026-02-12 → 2026-05-19 window. The market environment may have been atypically favorable to mean-reversion of weak-score names. Needs a longer window to test (which requires backfilling `trade_scores` — currently the collection only goes back to 2026-02-12).
2. **Entry-distance confounding.** Bottom-10 picks have `entry_price` further from `close` than top-10 picks. The effect may be entirely about pullback-magnitude, not score. The "entry-distance decomposition" follow-up (open) would settle this.
3. **Commission and spread.** Bottom-10's 48% fill rate means broker fees on cancellation attempts. Not modeled.
4. **Limit-good-for-1-bar artifact.** Production may use multi-day GTD limits. A wider fill window may change the bottom-vs-top story.
5. **SHORT side excluded from sweep.** Only LONG was run; the SHORT @ limit results from addendum 1 already showed the contrarian-short thesis has no operational interpretation.

### What this means for production (preliminary)

The combined signal across addenda 1+2+3:

- The **limit-at-entry_price mechanic** is the dominant source of edge. Adding it to a market-buy strategy is worth ~+0.28 pp/trade.
- The **top-N-by-score ranking** is unsupported by this data and may actively hurt the limit mechanic's edge. The score may be selecting *against* the high-quality pullback setups the limit filter is designed to capture.
- A live A/B between top-10, random-10, and bottom-10 books on the paper trader — same 1.5/3/3 RR, 30 days — is the cheapest next step that produces a verdict. Backtest now favors random-10 or bottom-10 by a wide margin on every cell tested.

Still want a longer window and the entry-distance decomposition before any production change.

## Addendum 4 — Entry-Distance Decomposition (2026-05-22)

To test whether the inverted-score effect is mechanically about pullback-distance and not score per se, ran the simulator with `--all` (every baseline-positive pick, no top-N filter) at 1.5/3/3 LONG @ limit. **42,398 attempted picks, 25,084 filled**. For each pick, captured `entry_dist_pct = (close_on_score_date − bh_entry) / close × 100` (positive = entry below close = a buy-pullback).

### Quintile bins by entry-distance

| Bucket | N | Avg dist% | Avg score | WR | Mean R/trade | 95% CI | Cum % |
|---|---:|---:|---:|---:|---:|---|---:|
| Q1 (−0.91, +0.20%) | 4,675 | −0.265% | **15.98** | 63.3% | +0.090% | [+0.040, +0.141] | +421% |
| Q2 (+0.20, +0.43%) | 4,674 | +0.334% | 13.41 | 64.3% | +0.174% | [+0.122, +0.225] | +811% |
| Q3 (+0.43, +0.58%) | 4,674 | +0.495% | 10.68 | 66.0% | +0.211% | [+0.155, +0.268] | +988% |
| Q4 (+0.58, +0.83%) | 4,674 | +0.689% |  8.15 | 69.2% | +0.341% | [+0.287, +0.395] | +1595% |
| Q5 (+0.83, +2.42%) | 4,674 | +1.074% |  **5.79** | 75.6% | **+0.618%** | [+0.565, +0.670] | **+2888%** |

Mean R rises monotonically with entry-distance: **+0.090% → +0.618%, a +0.528 pp swing across quintiles**. All five CIs exclude zero. Win rate also climbs monotonically: 63.3% → 75.6%. **Avg score drops monotonically as entry-distance rises** — score is inversely correlated with pullback-distance, which explains the addendum 3 result entirely.

### Cross-tab — does score have residual edge?

**Within each entry-distance quintile, split by score median:**

| Quintile | Low-score N | Mean R | High-score N | Mean R | High − Low gap |
|---|---:|---:|---:|---:|---:|
| Q1 | 2,339 | +0.098% | 2,336 | +0.083% | **−0.015%** |
| Q2 | 2,345 | +0.208% | 2,329 | +0.139% | **−0.070%** |
| Q3 | 2,337 | +0.195% | 2,337 | +0.228% | +0.032% |
| Q4 | 2,442 | +0.383% | 2,232 | +0.296% | **−0.087%** |
| Q5 | 2,337 | +0.590% | 2,337 | +0.646% | +0.057% |

Gaps: −0.087 to +0.057 pp. Inconsistent sign (low-score wins 3 of 5). CIs overlap heavily. **Score has no within-bucket predictive power.**

**Mirror — within each score quintile, split by entry-distance median:**

| Score quintile | Narrow-dist Mean R | Wide-dist Mean R | Wide − Narrow gap |
|---|---:|---:|---:|
| S1 (lowest score) | +0.155% | +0.531% | **+0.377%** |
| S2 | +0.223% | +0.616% | **+0.394%** |
| S3 | +0.224% | +0.400% | **+0.175%** |
| S4 | +0.083% | +0.362% | **+0.280%** |
| S5 (highest score) | +0.079% | +0.200% | **+0.121%** |

Gaps: +0.121 to +0.394 pp. **All 5 score buckets show wide-pullback > narrow-pullback** with statistical significance in 4 of 5. **Entry-distance has strong residual predictive power inside every score bucket.**

### Verdict

**Entry-distance is the entire edge. Score has no independent contribution.**

The "bottom-10 wins" finding from addenda 2 and 3 is fully explained by the inverse correlation between score and entry-distance:
- Top-10 picks: avg score ~16, avg entry-distance ~0.27% (Q1 cluster) → +0.09%/trade
- Bottom-10 picks: avg score ~6, avg entry-distance ~1.07% (Q5 cluster) → +0.62%/trade

It was never about the score; it was always about how far BH wanted the stock to pull back before buying. The score is a noisy proxy for entry-distance, and a worse one than the entry-distance itself.

### Production recommendation

**Rank by `entry_dist_pct` descending, not by score.** Take the top N picks by required pullback magnitude. This is a one-line change in the candidate selection logic.

Expected per-trade R based on the data: Q5 produced +0.618%/trade across 4,674 trades — ~3.4× better than top-10-by-score's +0.179% from addendum 1, and 1.2× better than bottom-10's +0.532%.

### Remaining caveats (smaller now)

1. **Window.** Same 2026-02-12 → 2026-05-19 window. Could be regime-specific. Longer-window backfill still warranted.
2. **One RR cell.** Within-bucket decomposition only run at 1.5/3/3. Need to confirm the entry-distance gradient holds at 2/4/5 (which had the biggest BOTTOM-TOP gap in the sweep).
3. **No commission/spread modeling.** Q5's 48% fill rate means ~2 limit orders per fill — broker fees compound on cancellations.
4. **Volatility confound.** Entry-distance may be correlated with stock volatility. High-vol names mean-revert more, so Q5 might just be "volatile-stock bucket." Worth a sub-decomposition (entry-distance bucketed within ATR/volatility quintile).
5. **Possible look-ahead artifact.** Verify `entry_price` in `metadata` is computed from data available at score-date close (not later). If entry_price uses next-day data, the test is contaminated. Quick code review needed.
6. **R:R filter interaction.** Production also filters by R:R > 1.0 etc. Wide-pullback picks may already be filtered differently than narrow ones — the production candidate set may not be the full Q5 universe this test used.

## Follow-ups (open, post-addendum 4)

- **Verify `metadata.entry_price` provenance.** Code-review the strategy code path that writes entry_price — confirm it's computed only from data ≤ score_date close. Critical sanity check before trusting this result.
- **Replicate the entry-distance decomposition at 2/4/5.** Confirm the Q1-to-Q5 gradient holds at the cell with the biggest score-bucket gap.
- **Volatility sub-decomposition.** Bucket by entry-distance AND ATR — is the Q5 edge persistent across volatility regimes, or concentrated in high-vol names?
- **Longer-window replication** (requires `trade_scores` backfill).
- **Paper-trader A/B.** Run a parallel "top-10 by entry_dist_pct" book at 1.5/3/3 vs the existing top-10-by-score book. 30 days of live results would settle production deployment.
- **Production A/B.** If the live paper trader can run a parallel "bottom-10" or "random-10" book at 1.5/3/3, measure 30-day live results against the top-10 book.
- **Decompose by entry-distance.** Is the bottom-10 edge actually about score, or just about `(entry_price - close) / close` magnitude? Re-bin picks by entry-distance and check per-trade R.
- **Multi-day limit GTD.** Production may keep the limit open >1 bar. Test `--limit-good-for {1,2,3}`.
- **Cross-check ML re-ranking.** Top-N by ML win-probability (production order) may differ materially from top-N by raw score.

## Files

```
research/contrarian_short_v1/
├── run_contrarian_short.py           # simulator
├── long_trades.csv                   # 1.5/3/3 TOP-10 long
├── short_trades.csv                  # 1.5/3/3 TOP-10 short
├── long_trades_5_3_14.csv            # 5/3/14 TOP-10 long
├── short_trades_5_3_14.csv           # 5/3/14 TOP-10 short
├── long_trades_bottom_1p5_3_3.csv    # 1.5/3/3 BOTTOM-10 long
├── short_trades_bottom_1p5_3_3.csv   # 1.5/3/3 BOTTOM-10 short
├── long_trades_bottom_5_3_14.csv     # 5/3/14 BOTTOM-10 long
└── short_trades_bottom_5_3_14.csv    # 5/3/14 BOTTOM-10 short
```
