# BlueHorseshoe Research

> Reset 2026-06-25. The prior tree was retired because too many results were tainted by
> inconsistent testing (unbounded forward returns, biased de-overlap, mid-price fills, premature
> verdicts). This skeleton exists so every new study starts from one agreed harness standard.
>
> **The bar for any result that leaves this directory:** it survived the harness below, and the
> number is the *signal*, not the *harness*.

---

## 0. The two products (different eval bars)

- **GORDON** = US equities, IBKR, **long-only**, short hold (≤ ~1 month), every trade stop-protected.
- **BUD** = forex / FTMO, OANDA, H4, long **and** short, per-trade stop.

The eval bar differs by product — do not import one into the other.

| | GORDON (long-only equity) | BUD (forex H4) |
|---|---|---|
| Pass bar | robust per-trade money in the **normal regime** | per-trade total money (sum of R), profitable A ∧ B ∧ holdout |
| "Mostly beta?" | not a defect — beta is harvestable, we're long regardless | n/a |
| "Beat random?" | optional (is the detector earning its keep), **not** a validity gate | optional floor only |
| Account / FTMO drawdown | not a per-trade concern | **excluded** — Brand owns the place/skip decision; no FTMO-constrained book sims unless asked |
| Catastrophe | Brand is the circuit-breaker; backtest the normal regime, not Armageddon | same |

**Makes money, not beats random** ([[feedback_makes_money_not_beats_random]]): the pass/fail bar is
*does it make money after costs*. If the system makes money and random also makes money, we do **not**
reject it. Random is a **floor** — the only random concern is being *worse* than random.

---

## 1. The clean harness (the standard for every study)

Three layers. First-pass screens run Layers 1–2; deployment candidates add Layer 3. **Run RAW and
CLEANED in the same pass and print a per-guard DELTA column** so we can see which contaminant moved
which number.

### Layer 1 — hygiene (kills the tainted-number failure mode)
- **Bracketed outcomes in R, worst = −1R.** Never unbounded raw forward returns `c[t+h]/c[t]-1`
  (split/delist tails produce divide-by-zero and fake −16% means). Win = +target_R, loss = −1R,
  timeout = fractional `(close_at_exit − entry) / risk_distance`.
- **Volatility floor:** `atr_pct ≥ 0.005` (drop dead stocks).
- **Dollar-volume floor:** `close · vol20 ≥ $1M` for screens; **$25M** for "is it tradeable on liquid
  names" claims (microcap mirages don't count).
- **Split/delist guard:** default (a) trust the adjusted-price source + winsorize residual tails;
  fall back to (b) "skip if the forward window has a > Nσ overnight gap" **only** if a data audit
  shows the OHLCV store holds RAW (unadjusted) prices.

### Layer 2 — statistics (kills the fake-significance failure mode)
- **Keep ALL firings.** Do **not** de-overlap. A flat N-bar de-overlap block is a *biased* estimator
  for mean-reversion/dislocation signals — it keeps the onset bar (worst entry) and discards the
  deeper-in-run bars where the reversion lives, and can **flip the sign** of a real edge
  ([[project_deoverlap_signflip_newey_west]]). Prior de-overlapped nulls may be false negatives.
- **Correct the SE for overlap with Newey-West** (Bartlett kernel, bandwidth **L = hold − 1**). The
  kernel weight `(N−j)/N` is literally the forward-window overlap fraction.
- **Symbol-clustered SEs** as the complement (cluster = symbol-weighted, NW = trade-weighted; a gap
  between them means the edge is concentrated in few-firing symbols — report it, don't hide it).
- **Matched random-entry benchmark** with the *same* filters and spacing. Random must read ~0.000R;
  if it doesn't, the machinery is non-neutral — fix it before trusting any cell.
- **Temporal robustness = per-calendar-year**, demeaned vs that year's same-regime random. Do **not**
  use a single chronological 2-bin split (it dumps COVID into one half). Time-split is a *regime read*,
  not a pass/fail gate.

### Layer 3 — faithfulness (deployment gate only)
- **Next-open marketable entry** + gap-aware stops, not close-to-close idealized fills.
- **Tiered cost stress** (the DeepOS / rsi cost model); confirm the edge survives at 10–20 bps.
- BUD fills: limit orders fill at **ask/bid touch exactly** — mid-touch ledgers over-count; model the
  spread in the *first* gate, not deferred (the BB "edge" that was pure mid-price noise is the lesson).

---

## 2. Validation split (out-of-sample)

Required for any deploy-recommend ([[bud_validation_split_interleaved]]):

1. **Interleaved quarter blocks** — assign each trade to half A or B by entry calendar quarter,
   alternating (Q1→A, Q2→B, Q3→A, Q4→B …). Every year (incl. COVID) lands in **both** halves.
   Require profitable in **A AND B**.
2. **Recent holdout** — hold out the **last ~24 months** entirely; compute A/B on pre-holdout data,
   then run the top settings **once** on the holdout (catches a recently-decayed edge).

A setting earns a deploy-recommend only if it clears **all three**: A ∧ B ∧ holdout.

**BUD eval objective** ([[bud_eval_objective_total_pnl]]): rank exit/setup candidates by **total R**
(sum of per-trade R at constant risk ∝ total dollars). Win rate is a byproduct — report, don't
optimize. **Exits (TP/SL/hold) are first-class free parameters**, not fixed. No portfolio /
account-drawdown / regime conditioning in the per-trade scoreboard.

**v2 gate** ([[project_v2_methodology]]) for BUD indicator cells: per-trade R with
`CI_low = mean_R − 1.96·SE > 0` on **both** walk-forward halves, N ≥ 50 (or 50/30 train/test).

---

## 3. Discipline (how to avoid the meta-failures)

- **No premature verdicts** ([[feedback_no_premature_indicator_verdicts]]). Explain the result and
  audit the harness *before* declaring anything dead. Let Brand steer.
- **Negative long-R ≠ dead** ([[feedback_trend_family_not_dead]]). These tests are long-only / 10d.
  A robust negative long-R is a **short-selector / long-avoid** candidate, not a no-information
  verdict. Never write an obituary.
- **The Eject** ([[feedback_the_eject]]) — SAFEWORD. If I flee hands-on inspection into opaque
  aggregate stats and start declaring a theory dead, Brand says *"The Eject"*: stop, go back to
  concrete examples. Stats are a clue to LOOK, not a verdict. Tally lives in `eject.txt`.
- **Prune on edge, not correlation** — a value-redundant signal can still carry incremental edge;
  only prune on an incremental-edge test.
- **Test indicators independently first** — solo-edge sweep over the indicator's own timeframe + RR
  before deciding role (strong solo edge → standalone strategy, not amplifier).
- **No silent caps.** If a run bounds coverage (top-N, sampling, no-retry), say so.

---

## 4. Directory conventions

```
research/
  README.md            ← this file (the standard)
  _lib/                ← shared reference harness (copy/import; validate per study)
    harness.py         ← bracketed-R, vol/$vol floors, clustered + Newey-West SE, random benchmark
  _template/           ← scaffold for a new study — copy to research/<study_name>_v1/
    STUDY_README.md
  <study_name>_v1/     ← one study per directory, versioned
    STUDY_README.md    ← question, method, status, verdict (start here every session)
    *.py               ← runners (print their own ledger; reproducible)
    *.csv / *.out      ← outputs (regenerable; large ones gitignored)
```

- **One study per directory, `_v1` suffixed.** A re-do that changes method gets `_v2`.
- **Every study dir starts with `STUDY_README.md`** — the question, the harness used, current status,
  and the honest verdict (OPEN / null / validated). It is the session handoff.
- **Runners print their own ledger.** A result you can't reproduce from the script doesn't count.
- **Data inputs** live in `data/*.parquet` (regenerated by `src/bluehorseshoe/maintenance/data_pulls/`),
  never inside `research/`. OHLCV comes from the DuckDB store.
- **Verdicts that survive the harness** get promoted to an auto-memory `project_*` note + (if shipped)
  a doc under `docs/`. The memory index is the institutional record, not this tree.

---

## 5. Pre-result checklist

Before any number leaves a study:

- [ ] Outcomes bracketed in R (worst −1R), not raw forward returns
- [ ] Vol floor + dollar-volume floor applied (and the tier stated)
- [ ] Split/delist guard active (or audit shows it's unnecessary)
- [ ] All firings kept; SE via Newey-West (L = hold−1) **and** symbol-clustered
- [ ] Matched random benchmark reads ~0.000R (machinery is neutral)
- [ ] Per-year temporal read (not a 2-bin split)
- [ ] For deploy: next-open fills + tiered cost stress survived
- [ ] OOS: profitable in interleaved A **and** B **and** the 24mo holdout
- [ ] RAW-vs-CLEANED DELTA column shown (the contaminant is visible)
- [ ] Verdict framed as a door, not an obituary; harness audited before any "dead"
