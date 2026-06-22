# S/R on H4 FX — Session Handoff (updated 2026-06-22)

## Read this first — orientation
This is a **live, promising** thread with **two validated edges already in hand** (buying
support AND selling resistance, both make money after costs across all 40 pairs). It is NOT
closed. Your job is to keep finding HOW to capture and extend the edge, not to declare things
dead.

How Brand wants this worked (he has had to correct these repeatedly — take them seriously):
- **Plain language, no jargon.** Say "makes about +0.16 per trade," not "netR +0.16, t=9."
  Frame everything as money. He judges by total money after costs; beating random is NOT required.
- **Never eject.** A null closes ONE door — turn to the next. When a result looks negative, first
  ask "is my *test* wrong?" and "how could this differ across pairs / conditions?" before concluding.
  (This session the headline "strength failed" turned out to be a measurement artifact — see below.)
- **Don't drive / don't end with a binary.** Report the state plainly and let Brand steer. He keeps
  a tally of premature door-closings; don't add to it.
- **Shorts are allowed on FTMO** — use them. (They're now a validated edge, see below.)
- Charts can't be seen in-terminal — **email them**: `EmailService().send_file(path, subject, body)`
  from `src/bluehorseshoe/core/email_service.py` (set `EMAIL_RECIPIENT=brandg@gmail.com`). Brevo;
  queued ≠ delivered.

## What's SOLID now (build on it)
**Recognition (settled — Brand's spec):** body-anchored pivots, **k=3** (±3-bar pivot window),
**min_touches=3**, **recency-weighted** levels (halflife=400 H4 bars: recent touches define a
level's strength and price), tol=0.0012, min_gap=0.0025, top_n=12. Walk-forward: trailing
1200 bars, re-detect every 120. All wired through `cluster_pts`/`levels_from`/`detect_levels_body`.

**Two validated edges (full 40-pair, after real spread, positive in both history-halves + holdout):**
- **Buy the "good bounce" off support: ~+0.17 per trade** (n=7507). dirn `above`.
- **Sell the "good bounce" off resistance (SHORT): ~+0.145 per trade** (n=7146). dirn `below`.
- A "good bounce" = the tag bar is **low-volume AND has a big rejection wick** (`sel` flag).
- Exit: 1-ATR stop + 2-ATR ratchet (ATR frozen at entry, cap 120 bars). A **plain fixed
  1-ATR-stop / 2–3-ATR-target works nearly as well** on good bounces — the exit is basically solved.

**Saved data — re-slice instantly, NO re-walk needed:**
`tickets_strength.parquet` (58,321 tags, all 40 pairs) carries per tag: pair, ts, dirn, **strength**,
volz, wick, **sel** (good-bounce), heldR (ratchet), bailR, nextR (next-open entry), br2R/br3R +
win flags (fixed brackets). Most further analysis = read this file + a pandas groupby.

## What we KILLED this session (don't re-chase — reasons attached)
- **Stop-and-reverse / breakdown shorts** — dead end-to-end. The prior +0.51 was favorable
  *excursion*, not edge: breakdowns have symmetric run vs snap-back (~2.5 ATR each), reach +2ATR
  before −1ATR only 32% of the time (need >33%). No exit geometry fixes symmetric excursion.
  (`reverse_eval.py`, `reverse_mfe.py`)
- **Strength-stacking via an ABSOLUTE gate (str≥6/≥8)** — looked great on 6 hand-picked pairs
  (+0.28→+0.67) but went FLAT (~+0.16) on all 40. WHY: strength's scale isn't comparable across
  pairs (choppy pairs rack up bigger numbers), so an absolute cutoff mixes incomparable things.
  **Within-pair normalization partially revives it** (top-quarter-strength-within-pair → ~+0.23 vs
  +0.16) — real but much smaller than the mirage. (`per_pair_strength.py`)
- **No-cleverness deployable versions** — "hold every strong support" and "buy every strong
  support with a fixed bracket" both LOSE on the full set (~−0.05). The 6-pair positives were
  flattering-pair selection.
- **Buy the bar AFTER the touch** — turns the +0.16 good-bounce into −0.24. The good bounces run
  up too fast; the next-open price gives up ~0.40. You must rest at the level. (`entry_and_bracket.py`)
- **The "flip as a signal" idea** (strong-support-fails ⇒ short that pair) — no link (corr −0.03);
  shorts pay about equally regardless. (`long_vs_short.py`)

## The ONE open problem = the prize (entry timing)
The good-bounce edge needs TWO things that can't both be had: **knowing it's a good bounce** (only
confirmed once the H4 candle closes — low-vol & big-wick) AND **buying at the level** (price has
moved off it by the close). Waiting kills it (−0.24); strength was the hoped-for shortcut and
doesn't generalize. **The gap is worth ~+0.4 per trade.** The exit is solved; this is the whole game.

## Live forward doors (pick one, measure, stay honest)
1. **A pre-close proxy for "good bounce"** — features knowable BEFORE the candle closes (approach
   speed/geometry, prior-bar structure, where the level sits in range, distance travelled in).
   Highest value: it directly attacks the entry-timing prize. Pre-tag *volume regime* was already
   flat — try the geometric ones.
2. **Per-pair DIRECTION map.** Shorts make money on ~11 pairs where longs don't (CAD_CHF, AUD_CHF,
   USD_PLN, USD_CZK, AUD_USD, …); some pairs are buy-only (USD_NOK, CAD_JPY, USD_SEK); some both
   (USD_JPY, USD_CHF, EUR_CZK). Open question that gates this: **is a pair's buy/sell preference
   stable over time, or is it just history?** (persistence test — untested, decides everything.)
3. **Within-pair strength** as a smaller secondary filter (needs a rolling/expanding rank to be
   look-ahead-free; current top-quarter result uses full-history ranking).

## Key files (`research/sr_forex_v1/`)
- Detection: `srlook.py` (`cluster_pts` w/ recency, `thin`), `approaches.py` (`detect_levels_body`,
  `find_tags`, `atr`), `reversal_size.py` (`load_px`, `levels_from`).
- Ticket pipeline: `ticket_gen.py` → `tickets.parquet` (current detector, no strength).
- Bundled analysis (carries strength + all exits, saves `tickets_strength.parquet`):
  **`confirm_full.py`** — full 40-pair, ~25 min. (Bug fixed: the walk-forward `t += STEP` was once
  missing → infinite loop on block 1; it's there now. If a run pins one core with 0 pairs printed,
  check loop increments first.)
- Slice/analysis (instant, read the parquet): `per_pair_strength.py`, `long_vs_short.py`,
  `size_by_strength.py`, `stacking_test.py`, `entry_and_bracket.py`.
- Charts (email): `chart_trades.py` (price + S/R + every buy/exit; levels drawn ONLY where the
  walk-forward had them live — no look-ahead), `latest_supports.py`, `why_no_touch.py`,
  `what_is_the_line.py`, `whats_special.py`.
- Diagnostics: `probe_blocks.py` (per-block heartbeat for one pair — use to localize slow/wedged runs).

## Process / safety notes
- Heavy runs OOM-risk the 7.8GB box during the **00:30–03:30 UTC** nightly maintenance window —
  run the ~25-min `confirm_full` outside it. `confirm_full.py PAIRNAME` runs a single pair (~25s)
  for quick checks.
- `tickets_pre_recency.parquet` is the pre-recency baseline; safe to delete once you're done
  comparing.

## What's genuinely settled (don't re-litigate)
- Recognition is good (k=3, 3-touch, recency, body-anchored) — Brand's spec, edge confirmed robust to it.
- S/R as a *selection* signal is closed; the value is the **bracket + exit on the good-bounce fade**,
  in **both directions**.
- The deployment blocker is **entry timing**, not level quality and not (pooled) strength.
