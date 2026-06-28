# opening_range_fade_v1

> Session handoff. Re-read before continuing. Intraday US-equity study (1-min bars).

## Product
GORDON-adjacent (US equities), but **intraday**, not the daily swing book. The daily-bar R
harness in `research/_lib` and README §1 does **not** apply here (no daily brackets, no H4). The
rigor standard used instead: out-of-sample split + a second untouched period + cost stress +
per-quarter robustness + a cross-sectional generalization test.

## Question
Does the "Touch-and-Turn" opening-range fade from a YouTube video (ProRealAlgos, "This 1 Minute
Scalping Strategy Works Everyday") have a real, cost-surviving edge — and if a variant does, where?

## The strategy
First 15-min candle (09:30–09:44 ET) sets H_15, L_15, R_open. Trade only if R_open ≥ 0.25·ATR_14
(daily). Red opening candle → BUY limit at L_15; green → SELL limit at H_15. Target = 0.382·R_open
back into the range, stop = 0.191·R_open beyond the extreme (2:1). Tradeable window 09:45→11:00.
- **Variant A** ("extreme must hold"): skip if the opening low/high was printed in the last K minutes.
- **Variant B** ("must bounce first"): arm the limit only after price lifts `BOUNCE_B`·R off the
  extreme. This skips the days that break straight down/up from the open (the falling-knife fades).

Units: `U` = the 1× stop distance (0.191·R_open). Target = +2U. All P&L net of 2¢/share unless "gross".

## Method
- Data: 1-min bars from AlphaVantage (`pull`), cached as JSON. Daily ATR from the DuckDB OHLCV store
  where the symbol is present, else a cached AV daily file. (DuckDB-first shifts the ETF/holdout ATR
  filter slightly vs the exploratory pass; verdicts unchanged.) Intrabar ties (a bar touching both target and stop)
  resolve pessimistically as a loss; this almost never fires at 1-min granularity (0 of 169 on the
  train set), so the fill numbers are trustworthy.
- Parameters locked on the train window (recent 21 days); **never re-fit on validation data.**
- Costs: flat ¢/share round-trip (defensible — these are penny-quoted). "Break-even cost" = the
  ¢/share at which net P&L hits zero = the margin of safety.

## Runners
`./run.sh python research/opening_range_fade_v1/run.py <cmd>` — `pull | backtest | validate | etf |
holdout | charts`. (`pull` first to populate `.cache/`; ~520 AV calls for `all`.)

## Status
**VALIDATED (narrow, modest).** Reproduces from cache. Not deployed.

## Result / Verdict
- **Baseline (the video as-is): loser.** −55 U out-of-sample over 1857 trades. The "+4 U" on the
  21-day window was noise.
- **Variant A: failed OOS** (negative at every K). In-sample win was overfitting. Dead door.
- **Variant B ("must bounce first", b=0.2): survived.** 12-stock OOS +92.5 U (+0.059 U/trade, win
  36.1% vs 33.3% breakeven). The OOS b-sweep peaks at 0.1–0.2, where training pointed. In 2025 Q3,
  when the baseline lost −79 U fading a trending tape, B made +10 U — the filter refused the knives.
- **Cost:** break-even ≈ 5.2¢/share on the mega-caps (real cost ~1–2¢) → real cushion.
- **Index generalization: mostly FAILED.** Of 16 fresh index/sector ETFs, only 2 net-positive after
  cost. Cheap penny-quoted ETFs ($40–80) can't clear the spread; among high-priced ones it's a coin
  flip. The broad "trade lots of indices" idea is dead.
- **Second-period holdout (SPY/QQQ/IWM, 2024→2025/05, untouched):** net-positive aggregate
  (QQQ +19 U, IWM +13 U, SPY ~flat). **QQQ and IWM replicated net-positive across BOTH periods;
  SPY went flat in period 2.**

**Honest read:** a real but *narrow and modest* edge living in the most liquid index instruments
(QQQ, IWM, ~SPY). The dangerous "widen the stop" path was rejected (monotonic improvement = removing
risk control, not edge). The next door is the instrument the cost mechanism points to — **micro index
futures (MES/MNQ/M2K)**, which also fits a small ($4k) automated account (no PDT, built-in leverage).

## Doors still open
- [ ] Test on micro index futures (needs 1-min futures history — IBKR, not AlphaVantage).
- [ ] Small forward paper test on QQQ/IWM (the only true OOS left).
- [ ] A third year, if AV history allows, on QQQ/IWM.

## Eject note
Reached via concrete charts (failure cases emailed, NVDA falling-knife inspected bar-by-bar), not
aggregate-only. Keep it that way: when a number surprises, pull the individual trade and look.
