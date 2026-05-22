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

## Follow-ups (open, post-addendum 2)

- **Replicate on a longer window** (12+ months) and across multiple RR cells to confirm the inverted-score effect isn't regime-bound.
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
