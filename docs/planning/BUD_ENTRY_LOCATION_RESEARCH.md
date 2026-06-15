# Bud Entry-Location Research

**Status:** Research note / candidate design  
**Date:** 2026-06-15  
**Scope:** Bud / BH FTMO H4 forex prediction engine  
**Purpose:** Identify indicators that can improve entry location after a Bud cell fires.

---

## 1. Thesis

Bud already has a validated signal map: fixed H4 cells by `(strategy, pair, direction, entry_mode)`.
The next likely source of improvement is not another generic oscillator. It is a separate
**entry-location layer** that decides whether a fired signal should be:

- taken immediately at mid / market,
- worked as a one-bar limit,
- worked at a wider ATR-discounted location,
- sized down,
- skipped.

The entry-location layer should be evaluated separately from signal generation. A good signal at a
bad location can still be a bad trade; a mediocre signal at an unusually good location may be worth
taking.

---

## 2. Current Bud Mechanics

Bud evaluates a fixed set of production H4 cells in `src/bud/briefing.py`.

Cell schema:

```python
Cell(strategy, pair, direction, entry_mode, params)
```

The current production book includes:

- Mean-reversion / dislocation family: `stoch`, `bb`, `sma`, `ema`, `rsi`, `cci`
- Trend / conditional momentum family: `macd`, `atr`, `ichimoku`
- Held-back / special case: `candle`

Entry mode is already first-class:

- `mid`: enter at the signal bar close.
- `limit`: for longs, use the signal bar low; for shorts, use the signal bar high; valid for the next H4 bar.

Reference:

- `src/bud/briefing.py`
- `src/bud/auto_v2.py`

---

## 3. Candidate Entry-Location Indicators

### 3.1 Relative ATR Regime

**Verdict:** Highest-confidence candidate.

Research in `docs/planning/ATR_REGIME_v1.md` found that long mean-reversion entries perform better
when the pair is calm relative to its own recent volatility history.

Best current form:

- Metric: `ATR(14)` rolling percentile
- Window: `252` H4 bars
- Per-pair, causal / point-in-time
- Buckets:
  - low: 0-33
  - mid: 33-67
  - high: 67-100

P3 result:

- Winning schedule: `size_down_high_0_5`
- Low/mid ATR: 1.0x size
- High ATR: 0.5x size
- Strong-4 long MR book:
  - total R: `1157 -> 1237`
  - max drawdown: `664 -> 521`
  - return/DD: `1.74 -> 2.37`
  - throughput cost: `0%`

Interpretation:

High relative ATR is a poor entry environment for Bud's long MR cells. It should at minimum size
down entries, and may justify requiring a better price before entry.

Research use:

- Primary filter / size modifier for long MR entries.
- Possible entry-distance multiplier: high ATR requires deeper pullback before entry.
- Do not generalize blindly to shorts or trend cells.

---

### 3.2 Entry Distance / Pullback Width

**Verdict:** Highest-value pure "location" candidate.

The contrarian / entry-distance thread found that limit-at-entry-price was load-bearing for edge.
Wider ATR-discounted entries produced much better per-trade R than narrow entries.

Key finding from `docs/handoff/CONTRARIAN_NEXT.md`:

- `ENTRY_DISCOUNT_BY_SIGNAL` maps stronger stock scores to narrower entries.
- Wide entry-distance produced about `3.4x` per-trade R versus narrow entries.
- Cross-tab result: entry-distance had the edge; score had no residual edge.
- Provenance was checked: no look-ahead in `entry_price = close_on_score_date - atr_discount * atr`.

Important caveat:

That result comes from the equities / contrarian thread, not directly from Bud H4 forex. It should
not be copied as-is. The idea is worth transferring: test whether Bud trades improve when entries
require a deeper price concession.

Research use:

- For each Bud cell, sweep limit distance from signal close:
  - `0.00 ATR` / mid-close equivalent
  - `0.10 ATR`
  - `0.25 ATR`
  - `0.50 ATR`
  - `0.75 ATR`
  - `1.00 ATR`
- Measure fill rate, mean R, total R, R per slot-day, and FTMO drawdown.
- Separate fill-quality from signal-quality.

Possible deployment shape:

```text
entry_distance_atr =
  base_by_cell
  * atr_regime_multiplier
  * d1_alignment_multiplier
  * session_multiplier
```

---

### 3.3 Mid vs One-Bar Limit

**Verdict:** Already built into Bud; needs systematic per-cell retest.

Bud currently hardcodes each cell as `mid` or `limit`. The limit rule is simple and attractive:

- long limit = signal bar low
- short limit = signal bar high
- order expires at next H4 close

This is a concrete entry-location rule, not just a signal.

Research question:

For each `(strategy, pair, direction)` cell, should the live entry be:

- immediate mid,
- signal-bar extreme limit,
- ATR-discounted custom limit,
- no entry unless price revisits a specific part of the signal bar?

Required measurement:

- Mid-touch simulations are not enough.
- Use executable bid/ask-touch fill rules for limit entries.
- Record non-fills explicitly; total value must include missed winners and avoided losers.

---

### 3.4 D1 Alignment

**Verdict:** Good conditioner, not yet a primary entry signal.

Bud already computes D1 alignment:

- `with-trend`
- `counter-trend`
- `flat`

The inline diagnostic says with-trend trades carried about `3.3x` the per-trade R. Bud currently
uses this as an annotation. For `atr` and `candle`, counter-trend fires are flagged as historical
money-losers.

Research use:

- Do not simply suppress all counter-trend trades without testing; many MR setups are naturally
counter-trend.
- Instead, test whether counter-trend entries require a deeper location.

Candidate rule:

```text
with-trend: allow mid or shallow limit
flat: normal rule
counter-trend: require wider limit or size down
counter-trend + high ATR: skip or very small size
```

---

### 3.5 Session

**Verdict:** Cheap and likely useful, but needs cell-level evidence.

Bud already labels the trigger bar session:

- Asia
- London
- overlap
- NY
- closed

H4 forex behavior is strongly session-dependent. A mean-reversion signal in Asia may have different
fill and follow-through behavior than the same signal during London/NY overlap.

Research use:

- For each cell, bucket fires by session.
- Measure:
  - fill rate for limit entries,
  - mean R,
  - timeout rate,
  - stop-first rate,
  - target-first rate,
  - FTMO daily-loss contribution.

Possible deployment shape:

- Session-specific entry distance.
- Session-specific size multiplier.
- Session-specific maximum new orders.

---

### 3.6 Cell Quality Rank

**Verdict:** Useful tie-breaker, not enough by itself.

Bud already has `CELL_QUALITY_RANK`, sourced from recent historical edge at `TP=0.5R`.
It is used to prioritize scarce slots when caps or safety gates bind.

Issue:

The rank is not an entry-location metric. It says which cell has been better recently, not whether
the current fired bar is at a good price.

Research use:

- Keep as a prior / tie-breaker.
- Interact it with entry location:
  - high-quality cell can accept shallower entry,
  - low-quality cell requires wider entry or skips.

---

## 4. Proposed Composite: Entry-Location Score

Build an experimental score that is separate from the prediction signal.

```text
location_score =
  atr_regime_score
  + entry_distance_score
  + d1_alignment_score
  + session_score
  + cell_quality_prior
```

This should not replace `evaluate_cell`. It should only decide execution quality after a cell fires.

Initial scoring sketch:

| Component | Good | Bad |
| --- | --- | --- |
| ATR regime | low/mid w252 percentile | high w252 percentile |
| Entry distance | deeper pullback with acceptable fill rate | chase / shallow entry |
| D1 alignment | with-trend or tested MR exception | hostile counter-trend |
| Session | cell-proven favorable session | cell-proven hostile session |
| Cell rank | high recent rank | weak / negative recent rank |

Execution decisions:

| Score band | Action |
| --- | --- |
| Strong | take mid or shallow limit |
| Normal | use current cell entry rule |
| Weak | require deeper limit |
| Bad | size down or skip |

---

## 5. Research Plan

### Phase A: Build Fire Dataset

For every historical Bud fire, record:

- `strategy`
- `pair`
- `direction`
- `entry_mode`
- `trigger_ts`
- `signal_close`
- `signal_high`
- `signal_low`
- `ATR(14)`
- `ATR_percentile_w252`
- `D1_alignment`
- `session`
- `cell_quality_rank`

Reuse:

- `bud.briefing.CELLS`
- `bud.briefing.evaluate_cell`
- `bh_ftmo.indicators`
- `FxStore`

### Phase B: Entry Distance Sweep

For each fire, simulate multiple candidate entries:

Long:

```text
entry = signal_close - k * ATR
```

Short:

```text
entry = signal_close + k * ATR
```

Sweep:

```text
k in [0.00, 0.10, 0.25, 0.50, 0.75, 1.00]
```

Also include the current Bud rule:

- mid close
- signal-bar low/high limit

### Phase C: Outcome Simulation

For each candidate entry:

- executable spread-aware fill rule,
- one-H4-bar fill window unless explicitly testing longer windows,
- same TP/SL/hold geometry as current Bud,
- long-MR exit override where applicable,
- no look-ahead in feature construction.

Metrics:

- fires
- fills
- fill rate
- mean R on fills
- total R including non-fills as zero
- R per slot-day
- win rate
- stop-first rate
- target-first rate
- timeout rate
- max drawdown
- FTMO max-loss breaches
- FTMO daily-loss breaches

### Phase D: Conditioner Tests

Run the entry sweep under these slices:

- ATR low/mid/high
- D1 with-trend/counter-trend/flat
- session
- cell quality tercile
- long MR strong-4 vs full book
- long vs short
- mid cells vs limit cells

Important: judge at the sleeve/book level where appropriate, not only per-cell. The repo's method
record repeatedly shows per-cell gates can be underpowered while the book-level effect survives.

---

## 6. Guardrails

1. **No generic indicator transplant.** VWAP, extra oscillators, or stock-style scores should not be
   first-line candidates for Bud entry location unless they beat the existing location evidence.
2. **No mid-touch shortcut for limit entries.** Limit studies must use executable bid/ask touch.
3. **No score conflation.** Signal score and entry-location score are different layers.
4. **No per-cell-only kill.** Use book/sleeve tests with Newey-West or date-clustered errors.
5. **Separate fill quality from prediction quality.** A lower fill rate can still be better if it
   filters bad locations, but total R and R/slot-day must prove it.
6. **Respect FTMO constraints.** A location rule that improves R but worsens daily/max-loss behavior
   is not deployable.

---

## 7. Expected Best First Experiment

Start with the long mean-reversion strong-4 book:

- `bb`
- `rsi`
- `ema`
- `stoch`

Why:

- This is where ATR-regime evidence is strongest.
- It already has special exit geometry in Bud.
- It is coherent as one sleeve.

Experiment:

```text
For every historical long-MR strong-4 fire:
  compute ATR w252 bucket, D1 alignment, session
  simulate entries at current mid rule, signal-bar low, and k*ATR pullbacks
  apply TP 1.5%, SL 1.0%, 10-day hold for validated long-MR cells
  compare unconditioned vs location-conditioned execution
```

Primary question:

Can a location-conditioned entry rule beat the current fixed entry rule on total R and FTMO
drawdown without unacceptable throughput loss?

Secondary question:

Does high ATR need only size-down, or does it need a deeper entry / skip?

---

## 8. Candidate Deployment Shape

If the experiment survives:

```python
def entry_location_policy(cell, features):
    if cell in long_mr_strong4:
        if features.atr_bucket == "high":
            return size_down_or_deeper_limit
        if features.d1_alignment == "counter-trend":
            return deeper_limit
        if features.session in hostile_sessions_for_cell:
            return deeper_limit_or_skip
        return current_entry_rule
    return current_entry_rule
```

Keep the first production version conservative:

- annotate first,
- then dry-run shadow decisions,
- then size-down,
- only later skip or alter entry price.

---

## 9. Open Questions

- Does entry-distance edge transfer from equities / contrarian work to H4 forex?
- Is the best location rule universal across long MR, or cell-specific?
- Does D1 counter-trend require deeper entry, or does it simply identify bad trades?
- Which sessions are hostile after controlling for pair and cell?
- Does high ATR hurt because entries are bad, exits are too tight, or both?
- Does a deeper limit improve R but starve the FTMO slot engine of enough trades to matter?

---

## 10. Source Pointers

- Bud cell definitions and evaluators: `src/bud/briefing.py`
- Bud autonomous execution loop: `src/bud/auto_v2.py`
- ATR-regime research: `docs/planning/ATR_REGIME_v1.md`
- ATR P3 result: `research/atr_regime_v1/ATR_REGIME_P3.md`
- Contrarian entry-distance thread: `docs/handoff/CONTRARIAN_NEXT.md`
- Executable limit-entry warning: `docs/planning/CONFLUENCE_SWEEP_v1.md`
- FTMO rule engine: `src/bh_ftmo/backtest/ftmo_rules.py`
