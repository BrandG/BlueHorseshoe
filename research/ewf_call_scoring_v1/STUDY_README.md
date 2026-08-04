# ewf_call_scoring_v1

> Session handoff. Start every session by re-reading this file.

## Product
Neither GORDON nor BUD directly — this is a **vendor evaluation** study of
elliottwave-forecast.com (EWF, "Blue Box" Elliott Wave subscription service, $99–$399/mo).
Scoring conventions are imported from the research standard (bracketed R, all-firings,
NW/clustered SE, null benchmark). If EWF calls score well, the downstream question is
GORDON-shaped: does EW confluence add bounce probability on top of our own S/R zones
(`linear-nibbling-meerkat.md` sleeve).

## Question
Do EWF's public, timestamped blog forecasts (direction + target + invalidation) make money
when scored with a pre-committed bracketed-R rule, and do they beat a trend-following null?

## Hypothesis
Prior: no net edge after the unscoreable/ambiguous posts are counted honestly — the method's
escape hatch ("alternate count") should show up as either vague posts (no scoreable triple) or
post-publication edits. But the archive is large (7,540 posts, back years) and the calls we
sampled DO state numeric targets + invalidation, so the test is real, not a strawman.
Secondary hypothesis: `modified` timestamps will show material post-hoc editing (measurable
unfalsifiability).

## Method (pre-committed — see SPEC.md, frozen BEFORE any outcome is computed)
- Each post yields at most one scoreable call: instrument, direction, target level(s),
  invalidation level, all stated in the post. Missing any element → **unscoreable row with
  reason** (never silently dropped; the unscoreable rate is itself a result).
- Outcome: bracketed R from the first bar after publication. Target touched first =
  +|target−ref|/|invalid−ref| R; invalidation touched first = −1R; window timeout = marked
  at window-end close / risk distance. Windows: 30 trading days primary; 10 and 60 sensitivity.
- Same-bar both-touch on daily data = ambiguous bucket (reported; loss in conservative read).
- Null: same instrument/date/levels, direction set by (a) sign of 20-day return (trend null)
  and (b) coin flip (random null). EWF must beat (b) and the interesting bar is (a).
- Stats: all calls kept; instrument-clustered SE + NW for overlapping windows.
- Integrity split: posts with `modified` > 7 days after `date` flagged EDITED-LATE and
  reported separately (their content may be retro-fitted).

## Runners (run everything through `./run_research.sh`, never bare python)
- `scrape_posts.py` — Phase 1: pull full WP archive (posts + category/tag taxonomies) to
  `data/raw_pages/`. Resumable, 1 req/1.2s. DONE.
- `compile_posts.py` — Phase 2: raw pages → `data/ewf_posts.parquet` + inventory report. DONE.
- `extract_calls.py` — Phase 3: blind LLM extraction (headless `claude -p`, Haiku) using
  `extract_prompt.md`. Resumable (skips post ids already in `data/calls.jsonl`).
  `--pilot N` for a stratified sample, `--workers N` for concurrency.
- `score_calls.py` — Phase 4: funnel-classify → price join → score → nulls → report.
  `--fetch` first (one-time OANDA H1 cache pull), then bare for scoring.
- `scoring.py` — pure engine, no I/O. Implements SPEC §2/§3/§4/§7 exactly.
- `instrument_map.py` — EWF instrument string → (source, symbol).
- `test_scoring.py` — 16 synthetic-bar tests, every outcome class + both call types.
  `./run.sh pytest research/ewf_call_scoring_v1/test_scoring.py`

## Data
- `data/raw_pages/` — raw API JSON (checkpointed scrape).
- `data/ewf_posts.parquet` — 7,540 posts, 2011–2026, with `edit_lag_days`.
- `data/calls.jsonl` — extracted calls, one row per post (resumable append).
- `data/calls_pilot_v1.jsonl` — archived v1-prompt pilot (superseded; kept for the record).
- `data/oanda_cache/{INST}_H1.parquet` — study-local H1 mid candles. Production FxStore is
  never written. `{INST}_UNAVAILABLE` marker = endpoint refused, reported as no-price-data.
- `data/scored.parquet` — one row per post: funnel stage + all R columns.
- Equities: `data/ohlcv.duckdb` read-only (12,550 symbols, 1999→).

## Gotchas found the hard way
- **`iter_candles_paginated` truncates this pull.** It stops on any short page, which OANDA
  returns mid-history — capping every instrument at 9,999 bars (~1.5yr). `fetch_oanda_cache`
  does its own `from`-cursor walk and stops only on empty page / non-advancing cursor / `end`.
- **The account instrument list is NOT the availability test.** `list_instruments()` returns
  68 FX-only pairs, but the v20 candles endpoint happily serves XAU_USD, SPX500_USD,
  NATGAS_USD, etc. Availability = try the endpoint, not the list.
- **Index/futures names collide with real US tickers.** EWF's `USDX` and `IBEX` are the
  dollar index and the Spanish index, not the Nasdaq-listed tickers of the same name — they
  would have silently mis-joined to equity data. See `EQUITY_DENY` in `instrument_map.py`.
- **Empty video/webinar posts** (88 posts, `text_len < 200`, mostly 2012–2013) make the
  extractor ask for the missing text. Those are reclassified `not-a-forecast` by `text_len`,
  not counted as extraction failures.

## Key recon facts (2026-07-28)
- WP REST API open: `/wp-json/wp/v2/posts` — 7,540 posts, 100/page = 76 pages.
- `date` AND `modified` both exposed. Sample TSLA post edited 1.5h after publication.
- Tags carry instrument names; categories include `bluebox-wins` (their victory-lap
  category — sample from EVERYTHING, never from that).
- Sample call (TSLA 2026-07-28): bearish, target range 290–189, invalidation 413.23 —
  a clean scoreable triple. Extraction is feasible.

## BLOCKED (2026-07-30): extraction needs spend headroom
Phase 3 is stopped at **766 / 7,540 posts** because the account's **monthly spend limit**
is exhausted (`claude -p` returns "You've hit your monthly spend limit"). Remaining work:
**6,761 real extractions, ~15.1M input chars (~4M input tokens) at Haiku rates.**
To resume, raise the limit at claude.ai/settings/usage, then re-run:
`./run_research.sh python research/ewf_call_scoring_v1/extract_calls.py --workers 4`

**Cheaper options if the budget stays tight** (each changes the funnel denominator, so
pick one and write it into SPEC before running — do not decide after seeing results):
- Stratified random sample of ~1,500 posts: ample power for a mean-R CI at ~22% of cost.
- Recent-era only (2019+, 4,588 posts): loses the early archive, keeps the modern product.
- An `ANTHROPIC_API_KEY` + the `anthropic` SDK (neither present today) would allow prompt
  caching on the ~800-token instruction prefix, which `claude -p` cannot reuse across calls.

### Extraction reliability (measured 2026-07-30/31, n=40 posts per cell)
Agreement of a fresh extraction against the stored single-post Haiku rows:

| field | Haiku single (floor) | Haiku BATCHED | codex single | codex BATCHED |
|-------|---------------------|---------------|--------------|---------------|
| instrument  | 100% | 95% | 92% | 98% |
| call_type   |  90% | **68%** | 75% | **80%** |
| direction   |  92% | 80% | 85% | 88% |
| is_forecast |  95% | 98% | 98% | 95% |
| levels      |  82% | 75% | 80% | 75% |

Readings:
1. **Batching is safe on codex, damaging on Haiku.** codex batched >= codex single, but
   Haiku batched sits 22 points below Haiku's own single-post floor on call_type.
2. **Extraction is not deterministic even single-post** (Haiku vs itself: call_type 90%,
   levels 82%). That is a ceiling on the study's precision, not a bug to fix away.
3. **call_type is the weak field, and it matters most** — it selects SPEC §3 vs §7.

Root cause, found by reading the disagreeing posts rather than the percentages:
**105 of 495 `directional` posts (21%) contain Blue-Box / equal-legs language.** EWF
routinely narrates a blue-box reaction that ALREADY happened and then gives a forward
continuation call ("USDCAD Forecasting The Rally From The Blue Box" — zone reached days
earlier). Prompt v2 classifies on vocabulary, so those posts are a coin-flip.
`extract_prompt_v3.md` (candidate) re-bases the rule on TIME — `zone_reaction` only if the
zone is still un-reached as of the post date — and is evaluated by `--selftest`
(same prompt, two independent passes) rather than against stored v2 rows, since a
deliberate rule change is supposed to change answers.

**Disclosure for pre-registration:** interim mean-R values were observed on 139 scored
calls from the partial (later purged) run before this prompt change was drafted. The
change is motivated solely by extraction self-consistency and the 105-post language count,
not by any outcome; it reclassifies posts between two populations that are both scored.
Recorded here so the amendment is auditable rather than invisible.

### The poisoning incident — read before trusting any calls.jsonl
The first full run hit the spend limit mid-flight and wrote **4,581 rows whose "call" was
the spend-limit error string**. Because resume keys on `post_id`, those rows would have been
**skipped forever** — a permanent silent hole masquerading as completed work, and the scored
funnel duly reported 4,573 `extract-error` rows as if that were a finding about EWF.
Purged (backup: `data/calls_poisoned_backup_*.jsonl`); `extract_calls.py` now treats
infrastructure failures as non-data: first hit sets an abort flag, no record is written, the
run exits 2 with an explanation. Verified live — the retry wrote 56 clean rows then aborted.
**Rule this encodes: an infrastructure failure is never a data point.**

## Status
OPEN, Phase 4 code complete (2026-07-28/30). SPEC.md FROZEN (incl. §7 zone_reaction addendum,
pre-registered after the pilot revealed the two-leg call shape but before any price data
was joined — no outcome had been computed at amendment time).

Phases: 1 scrape ✅ → 2 inventory + instrument map ✅ → 3 call extraction (full archive
running) → 4 price join + scoring (code done + unit-tested; awaiting full calls.jsonl) →
5 verdict vs nulls (+ incremental-over-our-S/R test if anything survives).

**The v1→v2 prompt revision is the one methodological judgement call to re-read before
trusting results.** The 20-post v1 pilot showed EWF's flagship "Blue Box" call is a two-leg
shape (price travels TO a zone, then reverses) whose zone sits on the *opposite* side of
reference from the eventual move. SPEC §2's sanity gate would have discarded all of them as
`levels-inconsistent` — i.e. the primary run would have silently excluded their signature
product. §7 + prompt v2 handle it as its own population with its own pre-committed rule.
Spot-checked v2 against source text: the retrospective-marketing guard works (posts that
replay a past win are `is_forecast=false` even when they carry full zone/pivot numbers).

## Result / Verdict (2026-07-31, full archive, codex+v3 corpus)

**No tradeable edge in EWF's public blog calls. The pass bar (SPEC §5: CI_low > 0) fails
for both call types, and their flagship Blue Box setup is the weaker of the two.**

Primary read, all scoreable calls, 30td bracketed R, ambiguous scored -1R:

| population | n | mean R | CI95 | vs random null |
|---|---|---|---|---|
| Type A directional | 1067 | +0.0155 | [-0.0440, +0.0750] | +0.018 (SE 0.043) |
| Type B +1R (filled)|  353 | -0.0059 | [-0.0960, +0.0842] | -0.12 (SE 0.088) on clean |

Both CIs straddle zero. Neither beats the coin-flip null with matched geometry. The 10td
and 60td sensitivities agree (Type A +0.013 / +0.024). Canary: random-null mean R read
+0.0004 / -0.0183 / -0.0024 / -0.0046 across the four blocks — machinery is neutral.

On the **clean (edit-lag <= 7d) subset only**, Type B is significantly negative:
mean R = -0.1252, CI95 [-0.2361, -0.0142], hit rate 24.3%, n=152.

### The funnel is the most substantive finding
Only **1,582 of 7,540 posts (21%) contain a complete, scoreable call** — 25% of the
forecast posts. What blocks the rest:

| reason | posts |
|---|---|
| no target stated | 2,016 |
| no invalidation stated | 968 |
| multi-scenario hedge (both directions, no primary) | 450 |
| levels inconsistent with reference price | 292 |
| not a forecast (education/marketing/retrospective) | 1,133 |

**Three quarters of EWF's forecast posts do not state a tradeable triple.** That is the
measured version of the unfalsifiability critique: not "their calls are wrong" but "most
calls cannot be graded at all, and the gradeable quarter is indistinguishable from noise."

### NO evidence of retro-fitting — and why the naive split says otherwise
SPEC §6's EDITED-LATE split is **confounded with era**: 2011-2016 posts are ~100%
edited-late, 2022-2026 are 1-14%, because old posts have had years to accumulate edits.
Era-matched on 2013-2019 (both strata present) the effect flips sign between call types
and neither is significant:

| | clean | EDITED-LATE |
|---|---|---|
| Type A | +0.1046 (SE 0.1305, n=140) | -0.0336 (SE 0.0472, n=316) |
| Type B | -0.0526 (SE 0.1321, n=48) | +0.0990 (SE 0.0675, n=185) |

Report the era-matched version; the raw split is an age artifact.

### Caveats that bound this verdict
- Tests the **public blog**, not member-area content. The paid product may differ — though
  that difference is exactly what cannot be verified before paying.
- Extraction is imperfect: levels agree 82-95% across repeat runs (see reliability table).
- The 30td window is OUR imposition, not their stated horizon (10/60 agree).
- Costs/slippage excluded per SPEC §8 — including them can only lower these numbers.

### Door closed, and what it opens
Phase 6 (does EW confluence add to our own S/R zones) was gated on something surviving
Phase 5. Nothing did, so that gate stays shut — do not buy the subscription on the strength
of public calls. What survives is **the rig**: a reusable vendor-scoring harness (blind
LLM extraction -> pre-committed bracketed-R -> matched nulls -> auditable funnel) that can
grade any vendor publishing timestamped public calls. The funnel metric alone —
"what fraction of your calls can even be graded?" — is a cheap first screen for the next
vendor, and can be run before any price join.

## Checklist (README §5)
- [ ] bracketed R, not raw forward returns
- [ ] all firings kept; NW + clustered SE
- [ ] random benchmark ~0.000R
- [ ] per-year temporal read
- [ ] unscoreable posts counted with reasons (auditable funnel)
- [ ] EDITED-LATE split reported
- [ ] verdict = door, not obituary
