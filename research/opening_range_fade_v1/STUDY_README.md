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
holdout | futures | charts`. (`pull` first to populate `.cache/`; ~520 AV calls for `all`.)
`futures` re-costs the validated SPY/QQQ/IWM edge in MES/MNQ/M2K terms (see `futures.py`).
`chart_futures.py` renders+emails the cushion chart. `paper_forward.py` is the forward MNQ
paper harness (`run_day` logs to `forward_paper_log.csv`). `gateway_pull.py` pulls REAL micro-futures
1-min+daily bars from the project's CME-entitled paper IB Gateway (4004) into the cache (ET-converted).
`forward_driver.py` (+ `run_forward_mnq.sh`, cronned) is the daily forward MNQ paper logger.
`analyze_losers.py` diagnoses losing quarters; `combine_portfolio.py` pools MNQ+MES+M2K (diversification).

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

## Micro-futures cost translation (2026-06-28, `futures.py`)
The README's futures rationale was the **cost mechanism**, so the first question — does the
edge clear *futures* costs? — needs no futures bars (edge is fixed in U; only cost-in-U changes).
Re-costing the validated SPY/QQQ/IWM Variant B edge into MES/MNQ/M2K (`run.py futures`):
- **Clears costs with margin in BOTH periods, all 3 instruments, all 3 cost scenarios.** The
  penny-spread problem that killed the broad-ETF version does NOT recur: per-contract round-trip
  ($1.24–2.50) is tiny vs the median 1U ($13–48/contract).
- **MNQ (QQQ analog) is the clear winner** — cushion 7–15× (P1), 4–9× (P2); exp ~$7–16/contract/trade.
- **MES (SPY analog)** solid — cushion 2.7–8.7× (P1), 1.8–5.9× (P2). SPY's weak P2 still nets positive.
- **M2K (IWM analog)** thinnest — cushion 1.5–3.7×; conservative P2 ≈ break-even (+$0.08/trade).
- **Caveat — this is a re-cost, not a fresh test.** It reuses the *ETF* price path. It does NOT test
  the one thing futures change: the 09:30-ET opening range on an instrument that traded all night
  (no gap/auction at the cash open). That still needs real futures 1-min bars.
- **Data source (resolved):** the claude.ai IBKR **MCP** has no CME data (controlled test: Sun 20:54 ET
  with CME open, equity 1-min served, MES/MNQ/M2K failed → entitlement gap, not the weekend). BUT the
  **project's own paper IB Gateway (127.0.0.1:4004) IS CME-entitled** — `gateway_pull.py` pulled 15,750
  real MNQU6 1-min bars + 62 daily (read-only, client_id=77). Gateway timestamps are Central; the
  ingest converts to ET. So real micro-futures bars are available in-house; no Databento needed.

- **Real-data corroboration (2026-05-08 .. 2026-06-26, front month MNQU6):** ran the validated Variant B
  on REAL MNQ bars (ATR-filtered). 14 fills, +$664/contract net (exp +$47/trade) — TINY sample. The signal
  is the **matched-date check: real MNQ vs the QQQ-path agree on side AND outcome 25/26 days.** The one
  divergence (2026-05-15) is a genuine intraday stop-vs-target ordering difference (QQQ hit stop first;
  MNQ filled-and-ran), not a bug — TZ/contract handling verified correct. **The re-cost is a valid proxy**;
  the "futures trade 24h, no opening auction" concern is largely immaterial for this strategy.

- **Roll-stitched REAL backtest (`gateway_backtest.py`, ~2yr, 9 quarterly contracts):** stitches the
  liquid front month per date (roll ~8d before expiry), ATR computed within each contract. Result over
  **211 real trade-days (2024Q3–2026Q2, all 8 quarters): 39.1% win — matches/exceeds the validated OOS
  (36%), now on REAL bars.** Net **+$1,887/contract central** (+$8.94/trade), conservative **+$1,682**
  (+$7.97/trade). **Chronological split both halves positive: first 60% +$1,347, holdout 40% +$540**
  (edge not stationary — holdout weaker — but stays positive OOS). **6/8 quarters positive** (losers:
  2024Q4 win 24%, 2026Q1 win 31%). The earlier +$47/trade taste was just the favorable May–Jun window;
  +$8.94/trade is the honest de-cherry-picked number. ~105 trades/yr × ~$9 ≈ ~$940/contract/yr on MNQ
  alone (intraday-only, flat ~11:00 ET → a $4k account margins 1 MNQ easily; MES+M2K would ~3× throughput).
  Pull notes: HMDS 1-min serves expired contracts back to ~Sept 2024 (MNQU4); MNQM5/MNQU5 needed
  retry+small-chunk fallback (`timeout=180`) — they time out on a single "2 M" request.

## Doors still open
- [x] **Real futures 1-min bars** — DONE via the project's paper IB Gateway (`gateway_pull.py`); CME
      entitled. Re-cost confirmed as a valid proxy (25/26 matched-date agreement on real MNQ).
- [x] **Roll-stitched real-futures backtest** — DONE (`gateway_backtest.py`): 211 trades over ~2yr,
      39% win, +$1,887/contract central, both chronological halves positive. Real-bar confirmation.
- [x] **Forward paper on MNQ — BUILT + CRONNED** (`forward_driver.py` + `run_forward_mnq.sh`,
      `10 16 * * 1-5` UTC in `ops/crontab.txt`). Logs one row/day to `forward_paper_log.csv` with an
      explicit status (no_session / pre_market / doji_or_thin / below_atr_floor / NEVER_FILLED /
      WIN|LOSS|TIMEOUT / fetch_error), idempotent per ET date; fetch_error AND pre_market are NON-terminal
      (retry next tick — a pre-window manual run can't poison the day's real capture). Replay- and live-
      verified. NOTE: Error 162 "connected from a different IP address" (account-wide — equity fails too)
      just means ANOTHER session is using the IBKR account's single data line; IBKR allows one at a time.
      Not an infra bug, not a wedge — clears when the other session disconnects. Driver logs fetch_error
      (non-terminal, retries) meanwhile, so no harm.
- [x] **Extended to MES + M2K** roll-stitched (`gateway_backtest.py MES|M2K`, `combine_portfolio.py`).
      MES (↔SPY): 140 trades, 43.6% win, +$962/contract, exp $6.87, both halves +. M2K (↔IWM): 259
      trades, 38.6% win, +$401, exp $1.55 (conservative just +$0.58 — thin). **Combined 3-instrument
      (1 contract each): +$3,250/contract/2yr, 610 trades, 39.7% win, 6/8 quarters +.** Diversification
      CONFIRMED: combined quarterly CV 1.02 < every single instrument (MNQ 1.42, MES 1.05, M2K 2.28);
      worst combined quarter −0.83× mean vs MNQ −1.53×. Losers don't align (MNQ −192 in 2026Q1 → −49
      combined). Only 2024Q4 stayed red (MNQ+M2K both lost; MES cushioned). Read: **MNQ+MES are the core
      (~$7–9/trade); M2K is an optional diversifier/throughput leg, thin standalone — include only if
      execution is cheap.**
- [x] **Probed the 2024Q4 / 2026Q1 losers** (`analyze_losers.py`): NO diagnosable regime. Trend-tape
      rejected (efficiency ratio identical, ~0.11, winners vs losers); direction rejected (winning side
      rotates quarter-to-quarter). It's variance on a modest edge — 2024Q4 z=-1.48 (p=0.07), 2026Q1
      z=-0.98 (p=0.16), neither clears 5%; 2026Q1's whole loss is 3 days (rest +$112). Losses are capped
      at 1U by design (no fat tail; big-$ losses are just large-range days). Takeaway: DON'T add a regime
      filter (would fit noise); expect ~25% red quarters; smooth variance via more instruments, not gates.
- [ ] A third year, if AV history allows, on QQQ/IWM.

## Eject note
Reached via concrete charts (failure cases emailed, NVDA falling-knife inspected bar-by-bar), not
aggregate-only. Keep it that way: when a number surprises, pull the individual trade and look.
