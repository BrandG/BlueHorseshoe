# EWF Call-Scoring Spec — FROZEN 2026-07-28, before any outcome was computed

This file pre-commits the scoring rule. Nothing here may change after the first scoring run.
Anything we later wish we'd done differently goes in a clearly-labeled sensitivity section of
the results, never into a rewrite of the primary rule. If a case turns up that this spec does
not cover, it is scored UNSCOREABLE with a reason — the spec does not get patched mid-study.

## 1. Unit of analysis
One **call** per post, extracted from post content only (the extractor — human, regex, or LLM —
sees the post text and NOTHING about subsequent price action). A call is the triple:

- `instrument` — from tags/title, mapped to a price series we hold (DuckDB equities, OANDA fx/metals/indices)
- `direction` — long/short, the post's stated bias
- `target` — stated numeric level(s); if a range, **primary = nearest to reference price**,
  sensitivity = farthest
- `invalidation` — stated numeric level on the opposite side of reference

A post missing any element → UNSCOREABLE with reason ∈ {no-instrument-data, no-direction,
no-target, no-invalidation, levels-inconsistent, multi-scenario-hedge, not-a-forecast}.
Every post gets a row. The unscoreable rate and reason mix are headline results.

`multi-scenario-hedge` = post gives both bullish and bearish counts with no primary bias.
`not-a-forecast` = educational/marketing post with no market call.

## 2. Reference price
First available price after `date_gmt` (publication): next daily-bar **open** for
equity-daily data; first H1 **open** after publication for OANDA instruments.
Sanity gates (else UNSCOREABLE: levels-inconsistent):
- target strictly on the direction side of reference; invalidation strictly on the other side
- risk distance |invalidation − ref| ≥ 0.1% of ref (degenerate brackets excluded)

## 3. Outcome (bracketed R, matching research/_lib conventions)
From the first bar after reference, walk forward:
- target touched first (bar high/low crosses it) → **win**, R = |target − ref| / |invalidation − ref|
- invalidation touched first → **loss**, R = −1
- both inside the same bar → **AMBIGUOUS** bucket: reported separately; conservative
  primary read scores it −1R; sensitivity drops the bucket
- neither within the window → **timeout**, R = direction_sign × (window_end_close − ref)
  / |invalidation − ref|, clamped to [−1, win_R]

Windows: **30 trading days primary**; 10 and 60 as sensitivities. Fixed for all calls
regardless of the post's own stated horizon (no discretion).

## 4. Nulls (computed on exactly the scoreable calls)
Same instrument, same reference time, same |target−ref| and |invalidation−ref| distances,
direction replaced by:
- **(a) trend null** — sign of trailing 20-trading-day return at reference (the interesting bar)
- **(b) random null** — coin flip, deterministic seed = post id (the floor)

## 5. Headline metrics (pre-committed)
1. Funnel: total posts → forecast posts → scoreable calls (+ reason mix) — auditability first
2. Mean R and total R of scoreable calls, with instrument-clustered SE and Newey-West SE
   (overlapping 30-day windows), all calls kept
3. Paired ΔR vs trend null and vs random null (same levels ⇒ per-call pairing is exact)
4. Per-calendar-year mean R (regime read, not a pass/fail gate)
5. Hit rate reported as a byproduct, never optimized

Pass bar (per house standard "makes money, not beats random"): mean R after the ambiguous
conservative read, CI_low > 0, and not worse than the random null. Beating the trend null is
the "is the wave-count adding anything" question — reported, not a validity gate.

## 6. Integrity splits (reported for every metric)
- **EDITED-LATE**: `modified_gmt` − `date_gmt` > 7 days → content may be retro-fitted;
  reported separately from the clean subset. (Archive-wide edit-lag distribution is itself
  a result: measured unfalsifiability.)
- Live-captured posts (scraped ≤ 7 days after publication, i.e. from 2026-07-21 onward and
  any future re-scrapes) are the tamper-proof gold subset as it accumulates.

## 7. ADDENDUM 2026-07-28 (pre-registered BEFORE any outcome was computed — pilot
## extraction revealed a second call shape; no price data had been joined at amendment time)

EWF's signature pattern is a **two-leg call**: "price should bounce/dip toward zone Z1–Z2,
then reverse, provided pivot P stays intact." The zone is on the OPPOSITE side of reference
from the eventual move — §2's sanity gate would discard these as levels-inconsistent, but
they are their flagship (Blue Box) call type, so they get their own pre-committed rule:

**Type B (zone_reaction) scoring:**
- entry = nearest zone edge, touched-limit fill: the call only activates if price reaches
  the zone within the 30-td window; never touched → NO-FILL row (reported, not a loss)
- direction = stated reaction direction; stop = pivot P → risk = |P − entry|
- their numeric reaction target is usually absent, so score fixed checkpoints:
  +1R-before-stop (primary) and +2R-before-stop (secondary), same ambiguity rules as §3
- if the post DOES state a reaction target, also score it as §3 with ref = zone-edge entry

Type A (directional, §3) and Type B are reported as separate populations; nulls for Type B
use the same zone/stop geometry with reaction direction from the trend and coin-flip nulls.

## 7b. ADDENDUM 2026-07-31 — call_type is decided by TIME, not vocabulary
### (extraction-reliability amendment; see the disclosure below)

§7 splits calls into Type A (directional) and Type B (zone_reaction), and that split
selects the scoring rule — so an unstable classifier contaminates BOTH populations.
Measured on 40 posts: Haiku agreed with its own earlier single-post answers only 90% of
the time on `call_type`, and 68% when batched. Reading the disagreeing posts showed the
cause is not model weakness but a genuine ambiguity in prompt v2: **105 of 495
`directional` posts (21%) contain Blue-Box / equal-legs language**, because EWF routinely
narrates a zone reaction that ALREADY happened and then gives a forward continuation call.

Prompt v3 (now `extract_prompt.md`; v2 archived as `extract_prompt_v2_archive.md`) re-bases
the rule on position-in-time:

> `zone_reaction` **only if the zone is still un-reached as of the post date** — price must
> still have to travel to it. If the post says the zone was reached, touched, or reacted
> from before publication, the call is `directional`.

**Why this is a correction, not a preference.** Checked against price data, **59 of 270
(22%) of v2's `zone_reaction` calls had a zone that price had ALREADY touched in the 20
bars before publication.** Under §7 those are unfillable by construction — the scorer waits
for a fill that had already occurred — which both inflates the NO-FILL rate and silently
removes real calls from the Type A population where they belong.

Validation used self-consistency (same prompt, two independent passes) rather than
agreement with stored v2 rows, since a deliberate rule change is supposed to change
answers. v3 scored 100% on call_type, direction and is_forecast (v2: 95/98/98) and was
correct on all five hand-checked hard cases.

**Pre-registration disclosure.** Interim mean-R values were observed on 139 scored calls
from the partial (later purged) extraction run before this amendment was drafted. The
amendment is motivated solely by extraction reliability — self-consistency rates, the
105-post language count, and the 22% already-touched measurement — and not by any outcome.
It moves posts between two populations that are both scored, in the direction dictated by
the price record rather than by results. Recorded here so the change is auditable.

## 8. Explicitly out of scope for the primary run
Costs/slippage (their calls aren't entries; R geometry is the object), position sizing,
portfolio effects, and the incremental-over-our-own-S/R test (Phase 6, only if something
survives Phase 5).
