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

## Follow-ups (open)

- **Re-run with limit-at-`entry_price` fills.** Compare LONG-with-limit vs LONG-with-open to quantify how much edge the limit mechanic preserves. If limit-LONG is profitable while open-LONG is negative, that's the production thesis confirmed.
- **Regime split.** Slice the window into pre/post a regime marker (e.g., SPY EMA200 cross or VIX bands) to see if the negative expectancy is concentrated in one regime.
- **Cross-check against ML overlay.** Top-10 ranked by `score` ignores the ML win-probability re-rank. Re-run on top-10 *after* ML re-ranking — that's what production actually trades.
- **Bottom-pool noise floor as a null benchmark.** Bottom-10 sits at ~0% mean R; future strategy tests can use it as a sanity baseline for "would random NASDAQ tickers do this well."

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
