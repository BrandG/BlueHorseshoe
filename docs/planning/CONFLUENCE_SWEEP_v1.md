# BH FTMO — Confluence Sweep v1 (Design)

**Status:** Design locked — not yet run. This is the build spec; results + verdict will be
appended (or land in `research/confluence_v1/CONFLUENCE_v1.md`) once executed.

**Date locked:** 2026-06-13

**Owner / product:** BUD (forex/FTMO). Lab = `bh_ftmo/`, cells consumed by Auto
(`src/bud/auto_trader.py`) via `bud.briefing` evaluators + the v2 CI gate.

---

## 1. Motivation

Every deployed v2 cell is a **single** indicator. The May 2026 sweep saturated the
single-signal, single-indicator H4 taxonomy (10 evaluators deployed; Donchian/SuperTrend/
ADX/Pivots tested → NULL). We have never systematically tested whether requiring **two
signals to agree** beats either alone. This is the cheapest unopened door because it reuses
every existing evaluator and the v2 harness end-to-end.

The equity side already built this methodology (`research/indicator_screen/confluence_test.py`,
`ha_confluence_gauntlet.py`) — its pure/all/BOTH control structure is mirrored here. It has
never been applied to BUD forex cells.

## 2. Hypothesis

**H:** Requiring two *independent* mean-reversion signals to agree on the same bar / pair /
direction produces higher per-trade expectancy than either signal alone, by enough margin to
justify the firing volume it sacrifices.

**Falsified if:** no `{A,B}` agreement cell beats `max(A_alone, B_alone)` by a CI-significant
margin with adequate surviving trades. A clean null here means single-signal is the H4
ceiling, and the next effort routes to relative-value (cross-pair cointegration) or the
exit side — **not** to more indicators.

## 3. Locked v1 decisions

1. **Strict AND only.** A confluence cell fires iff *both* components fire on the same closed
   H4 bar, same pair, same direction, same `entry_mode`. Voting (k-of-n) and asymmetric
   "confirm" logic are explicitly **deferred** — opened only if strict-AND shows life.
2. **Seed from the 33 deployed cells only.** For each deployed cell, pair it with each
   *orthogonal* partner evaluator on its own pair/direction. We do **not** sweep all 10×10 ×
   17 pairs × 2 dir from scratch — that invites noise-mining. Deployed-seed keeps the
   multiple-testing burden defensible.

## 4. The control-cell structure (the core of the method)

For each candidate pair `{A, B}` on a `(pair, direction)`, evaluate five cells:

| Cell      | Definition              | What it isolates                              |
|-----------|-------------------------|-----------------------------------------------|
| `A_all`   | A fires (B ignored)     | A's standalone edge                           |
| `B_all`   | B fires (A ignored)     | B's standalone edge                           |
| `A_pure`  | A & **not** B           | what A adds that B can't see                  |
| `B_pure`  | B & **not** A           | what B adds that A can't see                  |
| `BOTH`    | A & B                   | the confluence under test                     |

**Decision rule:** confluence is real iff
`mean_R(BOTH) > max(mean_R(A_all), mean_R(B_all))`
with the v2 CI gate passing on `BOTH` **and** surviving n ≥ floor (§7). If `BOTH` lands
between or beneath the components → redundant; deploy the better single signal instead.
`A_pure` / `B_pure` explain *why* (which component carried the marginal information).

## 5. The central risk — redundancy — and how P0 pre-empts it

Signal-independence found **41 indicators ≈ 3.7 independent factors**
([signal_independence](../../../.claude/projects/-root-BlueHorseshoe/memory/project_signal_independence.md)).
Most of the 10 evaluators collapse onto the same *dislocation* factor (Stoch ≡ W%R;
RSI / CCI / BB-lower all measure "stretched below"). AND-ing two of those just yields a
lower-volume slice of one signal.

**Phase 0 (do first, cheap):** regenerate factor grouping **on H4 forex** — reuse the
`signal_independence.py` fire-mask correlation approach against the 10 evaluators' fire masks
across the 17 pairs. Output: orthogonality clusters. **Only cross-cluster pairs are swept.**
Same-cluster pairs are reported as "redundant by design," not backtested. This converts ~45
strategy-pairs into a justified shortlist *before* any backtest, and pre-empts the "you found
a noisy slice" critique.

## 6. Combinatorial space

- 10 evaluators → C(10,2) = 45 strategy-pairs × 17 pairs × 2 dir = 1,530 raw.
- After P0 cross-cluster filter **and** deployed-cell seeding (pair each of the 33 deployed
  cells with each orthogonal partner on its own pair/dir): realistically **~50–150 `BOTH`
  candidates**.
- **Compute is free.** Forex data is 17 pairs × ~16k H4 bars — orders of magnitude smaller
  than the 2,000-symbol equity sweeps. **OOM is a non-issue; this can run anytime**, including
  outside the 00:30–03:30 UTC pipeline blackout. The candidate cap exists to control
  multiple-testing, not runtime.

## 7. Gate stack (v2 standard, applied in order)

1. **Expectancy CI:** `mean_R − 1.96·SE > 0` on `BOTH`
   ([v2 methodology](../../../.claude/projects/-root-BlueHorseshoe/memory/project_v2_methodology.md)).
2. **vs. components:** `BOTH` must beat `max(A_all, B_all)` — not merely beat zero.
3. **Newey-West (L = hold − 1)** on survivors; argue from NW-adjusted, **both-halves** stats,
   not raw per-cell mean_R (de-overlap is biased and sign-flips nonbull cells →
   [de-overlap → Newey-West standard](../../../.claude/projects/-root-BlueHorseshoe/memory/project_deoverlap_signflip_newey_west.md)).
4. **Executable ledger:** limit-entry cells scored on **ask/bid-touch** fills, not mid-touch
   (mid over-counts limit fills ~37% →
   [v2 live-R + fill model](../../../.claude/projects/-root-BlueHorseshoe/memory/project_v2_live_r_fill_model.md)).
5. **Throughput / book-level:** confluence trades *less*. A per-trade win that halves volume
   can lose at the book level → check $/day-per-slot and surviving trade count, not expectancy
   alone ([throughput over expectancy](../../../.claude/projects/-root-BlueHorseshoe/memory/project_tp_throughput_analysis.md)).

**n floor:** minimum surviving trades per `BOTH` cell to be eligible (proposed ≥ 40 over the
full sample, matching the thinnest deployed cells; final value set in P1 against observed
firing density).

## 8. Harness reuse / new code

**Reuse unchanged:**
- `src/bh_ftmo/backtest/{engine,gate,metrics,runner}.py` — backtest + v2 gate.
- `bud.briefing` evaluators (`_EVALUATORS`) + `evaluate_cell`.
- Walk-forward 70/30 protocol, 1%/1% RR, the standard H4 universe.

**New code (small):**
1. A `confluence` evaluator: AND of N component evaluators over the same `mid_df`. Registered
   in `_EVALUATORS` under `strategy="confluence"`.
2. A sweep driver in `research/confluence_v1/` that enumerates `{A,B}` from the deployed-cell
   seeds × P0 shortlist and emits the five control cells per candidate.

**No `Cell` schema change.** `Cell(strategy, pair, direction, entry_mode, params)` already
carries arbitrary `params`; a confluence cell is
`strategy="confluence", params={"components": [<cellA>, <cellB>], "logic": "AND"}`.

Look-ahead is already controlled: evaluators read the last *closed* bar only.

## 9. Phasing

- **P0 — Factor-group on H4 forex.** Fire-mask correlation of the 10 evaluators → orthogonality
  clusters → cross-cluster shortlist. Output: `factor_grouping.csv` + which pairs are
  redundant-by-design.
- **P1 — Pairwise confluence sweep.** Deployed-seed × P0 shortlist → 5 control cells each →
  CI gate + beat-components rule. Output: results CSV (one row per `{A,B,pair,dir}` with all
  five cells' mean_R / SE / n).
- **P2 — Re-gate survivors.** Newey-West + executable-ledger fills on P1 survivors. Output:
  the defensible survivor set.
- **P3 (only if survivors exist) — Triple confluence + deploy decision.** k=3 AND on the best
  pairs; book-level throughput; deploy-or-not call. *This is also the natural point to revisit
  the deferred voting / soft-confirm logic if AND survived.*

## 10. Deliverables

- `research/confluence_v1/` — P0 factor grouping, sweep script + `.out`, P1/P2 results CSVs.
- `research/confluence_v1/CONFLUENCE_v1.md` — verdict doc with the decision table per survivor
  (or the documented null).
- A memory rollup entry either way: survivors → candidate v2 cells (then wired into
  `bud.briefing.CELLS`); or a null that explicitly points to the next door (relative-value
  / exits).

## 11. Success criteria

- **Positive:** ≥1 `BOTH` cell clears all five gates *and* beats `max(A_all, B_all)` with
  NW-adjusted, both-halves significance and n ≥ floor → candidate cell(s) for v2 deployment.
- **Null (still a win):** no cell survives → single-signal is the H4 ceiling; confluence door
  closed; effort routes to relative-value or exit-side research. Report honestly, no silent
  top-N, log how many candidates were tested.

## 12. Open items deferred past v1

- Voting (k-of-n) and asymmetric confirm logic (P3 trigger only).
- Triple+ confluence beyond the P3 best-pairs probe.
- Cross-pair confluence (that is door #2, relative-value — a separate scope, not this sweep).
