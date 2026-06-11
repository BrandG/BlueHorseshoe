# Solvency-Filtered Bare DeepOS Sleeve — Production Wiring Spec

**Status:** SPEC / awaiting approval. Not wired. 2026-06-08.
**Research basis:** `[[project_fundamentals_quality_condition]]`. Solvency (Altman-Z″, book-only) orthogonally
splits the DeepOS bounce (Doors #1/#3/#2 all pass). Package re-validation (`fundamentals_package_revalidate.py`):
the HARD Z″<1.1 filter on a **nonbull-gated bare book** adds **+735 total$ bare-only, 90%CI[+195,+1385],
P=1.00** (decade, full universe). The nonbull gate is a *prerequisite* (solvency washes on the all-regime book,
−0.003 P=0.42). Net package vs production: positive point estimate (3× the $ on 23% of the trades), not
statistically certified — a modest, well-motivated efficiency/quality change.

## The package (two coupled changes)
1. **Nonbull-gate the bare `deep_oversold` sleeve** (currently ungated; only `deep_oversold_ha` gates nonbull).
2. **HARD Altman-Z″<1.1 filter on bare candidates** (drop known-distressed; keep unknown-Z; HA untouched — it
   already subsumes solvency).

HARD chosen over a graded tilt: simpler, ≥ tilt on the full universe, and **needs no Z″ winsorization** (the
formula's near-zero-liabilities blowups are huge-positive = solvent = kept, so the `<1.1` threshold is robust).

---

## Change 1 — nonbull-gate bare DeepOS
`src/bluehorseshoe/analysis/strategy_interface.py`, `DeepOversoldStrategy.process` / `process_worker` (~L836-843).
The module helper `spy_is_nonbull(benchmark_df)` (L35) and the worker's `benchmark_df` already exist (HA uses
them). Add the same front gate to bare, **behind a config flag** so it's reversible and A/B-testable:

```python
# in process_worker (and process, via ctx.benchmark_df):
if config.deep_oversold_nonbull_gate:           # new flag, default per rollout below
    if spy_is_nonbull(worker_state.get('benchmark_df')) is not True:   # fail-closed on unknown
        return None
```
- New `Settings` field `deep_oversold_nonbull_gate: bool` in `core/config.py` (+ `DEEP_OVERSOLD_NONBULL_GATE` env).
- Fail-closed (None/bull → no fire) mirrors HA's mandatory gate.
- ⚠️ Behavior change: drops all bull-regime bare fires (~75% of bare volume). This is the prerequisite for the
  solvency edge; on its own it is ~total$-neutral (M−A P=0.46).

## Change 2 — fundamentals feed (Altman-Z″ as-of, PIT)
**Storage:** new DuckDB table `fundamentals` in the existing `data/ohlcv.duckdb` (or a sibling `fundamentals.duckdb`):
`(symbol, reportedDate DATE, altman_z DOUBLE, fscore INT, ...raw TTM fields...)`. Seed from the validated research
parquet `data/fundamentals.parquet` (already built, 1,119 syms). Add a `DuckDBStore.load_solvency_asof(date)` →
`{symbol: latest altman_z with reportedDate <= date}` (PIT, no lookahead — the research-validated alignment).

**Refresh job:** `src/cron_quarterly_fundamentals.sh` (model on `cron_weekly_retrain.sh`; **must `source .env`** —
see `[[project_weekly_retrain_env_bug]]`, that bug bit the retrain cron). Wraps a resumable AV 3-statement pull
(generalize `research/indicator_screen/fundamentals_pull_full.py`): refresh ~weekly/quarterly (statements update
on earnings), recompute Z″ per quarter aligned to `reportedDate`, upsert into the table. Rate-limit-safe + gate
detection already in the puller. AV calls: ~3×N covered names; incremental (only refetch names with a new
earnings date since last run).

**Z″ definition (book-only, fully PIT from statements):**
`Z'' = 6.56·WC/TA + 3.26·RE/TA + 6.72·EBIT_ttm/TA + 1.05·(TA−TL)/TL`, distress `< 1.1`.

## Change 3 — solvency filter wiring (bare only)
**Inject** like `market_health`: add `'solvency'` to `shared_ctx` in the predict pipeline and to `_worker_state`
in `_init_worker` (`strategy.py` L1040). Value = `store.load_solvency_asof(target_date)` (one dict, picklable,
cheap). For the sync path, expose on `ctx` (`container`/`service`).

**Filter** in `DeepOversoldStrategy._evaluate` (or a dedicated `_solvency_ok`), behind a flag, **bare only**
(override to no-op in `DeepOversoldHAStrategy`):
```python
if config.deep_oversold_solvency_filter:
    z = (worker_state.get('solvency') or {}).get(symbol)
    if z is not None and z < DEEP_OVERSOLD_Z_DISTRESS:   # known-distressed only; unknown kept
        return None
```
- New constant `DEEP_OVERSOLD_Z_DISTRESS = 1.1` (constants.py).
- New flags `deep_oversold_solvency_filter: bool`. Applies to bare; HA excluded (subsumes solvency).
- **Missing data = keep** (don't penalize names without fundamentals — matches the sim's tilt-neutral handling).

---

## Config / flags (safe defaults)
`core/config.py` + env: `DEEP_OVERSOLD_NONBULL_GATE`, `DEEP_OVERSOLD_SOLVENCY_FILTER` (both default **False** →
zero behavior change until explicitly enabled). Constant `DEEP_OVERSOLD_Z_DISTRESS=1.1`.

## Rollout (mirror the dry-run discipline of bh_swing)
1. **Land dark (flags off)** + the fundamentals table/refresh + the as-of loader. No live change. Verify
   `load_solvency_asof` matches the research parquet on a few dates.
2. **Shadow:** log what each flag *would* drop on each `-p` run (counts + names) for ~2 weeks; eyeball vs
   `[[feedback_validate_before_deploy]]`.
3. **Flip solvency filter first** (the certain edge, P=1.00), nonbull-gate second (the prerequisite, bigger
   behavior change). Watch the hypothesis-engine forward-R and arcade report.
4. Keep the research scripts as the regression oracle.

## Testing
- Unit: `_solvency_ok` (distress drop / unknown keep / HA no-op); bare nonbull gate (fail-closed on None/bull).
- PIT: `load_solvency_asof(d)` never returns a `reportedDate > d`.
- Integration: a fixture symbol with a known Z″ history is filtered/kept across regimes as expected.
- Reporting: arcade/report sleeve counts reflect the gates (don't show filtered names as tradeable).

## Open items / risks
- **Not statistically certified** net-of-production over one decade (B−A P=0.59) — deploy as a modest
  efficiency change, not a blockbuster; the *solvency component* is certain (P=1.00).
- **Bigger levers still open** (out of scope here): HA `edge_weight`/allocation (over-allocates to a thin sleeve)
  and 10-slot crash-capacity. Likely larger than this filter — see memory.
- **Entry stop-compression** (`[[project_deepos_stop_compression]]`) is orthogonal and unfixed; this package
  doesn't touch the bracket. Equal across arms in the sim.
- Survivorship: delisted/distressed names absent from AV → the value-trap tail is under-sampled; the filter is
  conservative (keeps unknowns), so this biases *against* overstating the edge. OK.
