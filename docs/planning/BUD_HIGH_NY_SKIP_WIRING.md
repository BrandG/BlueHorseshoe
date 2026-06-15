# Bud high-ATR ∩ NY skip — wiring spec

**Status:** Spec for review (no code written)
**Date:** 2026-06-15
**Owner decision required:** §9
**Research provenance:** `research/entry_location_v1/` (P0–P4),
`docs/planning/BUD_ENTRY_LOCATION_RESEARCH.md`

---

## 1. What we're wiring

Skip the strong-4 long mean-reversion entries that fire **in a high-ATR regime during the
NY session** — the one entry-location corner that validated under the per-trade lens.

Evidence (per-trade R, mid entry, 1%/1%, MAX_HOLD=84):
- high-ATR ∩ NY = **−0.073 R/trade** (n=2,558), Newey-West significantly negative.
- ≈ the **entire** high-ATR drag (−186 R); high-ATR *outside* NY is +0.002 R (flat).
- Recent-24mo holdout: train −0.070 / holdout −0.086 (replicated, not decayed).
- Broad: 15/17 pairs negative; worst pair only 17% of the loss.
- **Skipping it lifts the strong-4 long book +186 R = +17%** (1112 → 1298).
- Does **not** generalize to shorts (flat) or to the full-6 extras (cci/sma dilute it,
  not NW-significant) — so the rule is deliberately scoped to strong-4 long only.

This is a **skip** (don't take the trade), justified purely at the per-trade level
(declining trades that lose money per trade). No account/FTMO framing.

---

## 2. The rule (single source of truth)

```
skip  ⟺  cell.strategy ∈ {bb, rsi, ema, stoch}
         AND cell.direction == "long"
         AND session_of(bar_ts) == "ny"
         AND atr_pct_w252(mid) ≥ 2/3        # the "high" ATR bucket (67–100 pct)
```

To prevent drift between research, briefing, and the autonomous trader, this predicate
lives in **one** function imported by both prod paths — proposed:

`src/bud/entry_location.py`
```python
STRONG4_LONG = frozenset({"bb", "rsi", "ema", "stoch"})
ATR_PCT_WINDOW = 252
ATR_HIGH_PCT = 2.0 / 3.0

def atr_pct_w252(mid) -> float:
    """Trailing-252 percentile rank of ATR(14)'s latest value (PIT, causal).
    Returns nan if < ATR_PCT_WINDOW finite ATR values are available."""
    a = atr(mid, period=14)
    window = a.tail(ATR_PCT_WINDOW).to_numpy(float)
    finite = window[np.isfinite(window)]
    if len(finite) < ATR_PCT_WINDOW or not np.isfinite(window[-1]):
        return float("nan")
    return float(np.mean(finite <= window[-1]))   # == research _rolling_percentile rank_last

def is_high_ny_skip(strategy: str, direction: str, bar_ts, mid) -> bool:
    if strategy not in STRONG4_LONG or direction != "long":
        return False
    if session_of(bar_ts) != "ny":
        return False
    pct = atr_pct_w252(mid)
    return bool(np.isfinite(pct) and pct >= ATR_HIGH_PCT)
```

Definition matches the research exactly (`atr_regime_p1._rolling_percentile` rank_last;
`sessions.session_label` for NY; `_atr_bucket` high = pct ≥ 2/3).

**Fail-open:** if `atr_pct_w252` is nan (data gap / new pair), `is_high_ny_skip` returns
False → the trade is taken and annotated "atr_pct unavailable." We never suppress on
uncertainty; the cost of a missed skip is one ~−0.07 R trade.

---

## 3. Precondition (verified)

`atr_pct_w252` needs ≥ 266 raw bars (252 percentile window + ~14 ATR warmup).
`LOOKBACK_BARS = 300` (`briefing.py:63`) satisfies it with ~34 bars margin, and both
prod paths already load the tail of that length. The trailing-252 value at the fire bar
is identical whether 300 or 10,000 bars are loaded — no full-history dependency.
**Guard:** if `LOOKBACK_BARS` is ever lowered below 266, the percentile silently goes nan
(→ fail-open, no skips). Add an assert in `entry_location.py` import.

---

## 4. Integration point A — briefing.py (human-in-loop)

`evaluate_fires()` already annotates each fire with `d1_align`, `session`, `ct_warn`
(`briefing.py:~842–855`). Add two fields, mirroring `ct_warn` (annotation, **not**
suppression — same as how D1/session shipped, per the briefing-annotations precedent):

```python
"atr_pct": atr_pct_w252(mid),
"high_ny_skip": is_high_ny_skip(cell.strategy, cell.direction, bar_ts, mid),
```

Surface in the console/email report: flag `high_ny_skip` fires (e.g. a `⊘ HIGH∩NY`
tag in the SIDE/notes column) and add a **funnel line** so a null is distinguishable
from a bug (per the auditable-surfaces standard):
`strong-4 long fires: N | high∩NY flagged: k | (skip would forgo k, recover ≈ k×0.07R)`.

Briefing never auto-suppresses — Brand sees the flag and decides. This is Phase 1 and
carries no behavior change.

---

## 5. Integration point B — auto_v2.py (autonomous)

The cell loop in `run()` (`auto_v2.py:~395–490`) already runs ordered gates that journal
`skip_*` events (`skip_margin_util`, `skip_already_open`, `skip_direction_imbalance`).
Add one more gate, immediately after `evaluate_cell` passes and before sizing:

```python
if HIGH_NY_SKIP_ENABLED and is_high_ny_skip(cell.strategy, cell.direction, bar_ts, mid):
    LOG.info("%s/%s: high∩NY skip", cell.strategy, pair)
    _append_journal_row({**base_fields,
        "event": "skip_high_atr_ny" if not dry_run else "would_skip_high_atr_ny",
        "note": f"atr_pct={atr_pct_w252(mid):.2f} session=ny"})
    continue
```

`HIGH_NY_SKIP_ENABLED` is a module constant (default per the rollout phase below) for
instant rollback without a code change to the loop.

---

## 6. Staged rollout (conservative, per research note §8)

| phase | briefing | auto_v2 | gate |
|---|---|---|---|
| **1 — annotate** | show `high_ny_skip` flag + funnel count | log `would_skip_high_atr_ny`, still place | `HIGH_NY_SKIP_ENABLED=False` |
| **2 — shadow/measure** | (same) | (same) | confirm flagged fires are the losers via `reconcile.py` outcomes over ~3–4 wks |
| **3 — live skip** | (same) | actually `continue` (no order) | `HIGH_NY_SKIP_ENABLED=True` |

Phase 1 ships dark — no trade behavior changes, we just watch the flag fire at the
expected rate (~6% of strong-4 long fires landed in high∩NY historically). Phase 3 is a
one-constant flip.

---

## 7. Scope guards (must NOT touch)

- shorts (effect is flat) — predicate gates on `direction == "long"`.
- cci, sma, and all non-strong-4 cells — `strategy ∈ STRONG4_LONG`.
- trend families (macd, atr, ichimoku, candle) — untested, excluded by the strategy set.
- limit cells — strong-4 are all `mid`; the predicate is mode-agnostic but only strong-4
  long cells satisfy it, and they're all mid.

---

## 8. Tests

- `test_entry_location.py`: predicate truth table (each strong-4 long + NY + high → True;
  short / non-NY / low-mid ATR / cci → False); nan atr_pct → False (fail-open);
  `atr_pct_w252` matches `research/.../_rolling_percentile` on a fixture series.
- briefing: a synthetic high∩NY fire is annotated `high_ny_skip=True` and counted in the funnel.
- auto_v2: with `HIGH_NY_SKIP_ENABLED=True`, a high∩NY cell journals `skip_high_atr_ny`
  and places no order; with False, it places and journals `would_skip_high_atr_ny`.

---

## 9. Decisions for Brand

1. **Rollout start** — ship Phase 1 (annotate-only, dark) first, or go straight to live skip?
   Recommend Phase 1; it's zero-risk and confirms the flag rate before any suppression.
2. **Skip vs size-to-zero** — a hard skip (no order) vs a 0.0× size that still journals a
   "shadow" intended trade for outcome tracking. Recommend hard skip; shadow tracking is
   already covered by Phase 1's `would_skip` journal.
3. **Briefing behavior** — annotate-only (Brand decides), or also annotate + recommend-skip
   text? Recommend annotate + explicit "research says skip" note, decision stays human.
4. **File placement** — new `src/bud/entry_location.py` for the shared predicate (proposed),
   vs folding into `briefing.py`. Recommend the separate module (briefing + auto_v2 both
   import it; keeps the rule single-source).

No code lands until these are settled.
```
