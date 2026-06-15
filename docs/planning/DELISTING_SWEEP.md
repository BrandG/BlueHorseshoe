# Delisting Sweep

**Status:** P0 shipped (read-only finder). P1–P3 proposed.
**Owner:** Gordon (equities) data hygiene.
**Related:** `src/bluehorseshoe/analysis/liquidity.py` (runtime gates, the mid-week
safety net this sweep complements); `project_gordon_liquidity_delisting_gates` (memory).

## Problem & value

~399 symbols (untraded ≥10 sessions) are dead/delisted but still `active=True` in
the `symbols` collection, so every `-p` run pays Phase-1 I/O (DuckDB load +
overview + sentiment fetch) for each, and the market-cap filter (`strategy.py`
~L916) trusts their zombie overviews — e.g. THR/Thermon still shows a $1.53B
`MarketCapitalization` with `updated_at: None` after delisting ~2026-05-29.

The runtime liquidity gates (`latest_bar_untraded` / `is_dead_series` /
`MIN_DOLLAR_VOLUME`) already keep these *off the report*, but the universe stays
bloated and the funnel/logs noisier. This sweep removes them at the source. The
gates remain as defense-in-depth for anything that delists *between* weekly sweeps.

## Census (untraded-tail = length of the leading zero-volume run)

Authoritative counts from the P0 finder (2026-06-15, `data/ohlcv.duckdb`):

| ≥N untraded sessions | symbols | active (sweep targets) |
|----------------------|---------|------------------------|
| ≥1  | 1066 | — |
| ≥5  | 490  | — |
| ≥10 | **399** | **245** (140 with a zombie market-cap) |
| ≥20 | 347  | — |

The 1066→490 drop (N=1→5) is the transient-gap zone burning off; the curve
stabilizes past N=5. **N≥10 is the confident set** — of those 399, **245 are still
`active=True`** (the sweep's real target) and **140 carry a zombie
`MarketCapitalization`** that currently passes the prediction mcap filter. Universe:
12,320 symbols in DuckDB, 12,490 in the `symbols` collection (all `active=True`).

> The finder counts the *run length* of the leading zero-volume tail, which is
> stricter than "most-recent-N-bars-all-zero" on short-history symbols (a 15-bar
> all-dead name reports `days_untraded=15`, not ≥20). Earlier exploratory numbers
> (622/531/499) were the looser variant.

## Design — two-signal, confirm-before-act

- **Finder (cheap, local):** untraded tail ≥ N sessions from DuckDB. Reuses the
  `liquidity` notion of an untraded bar, generalized to a run length. Default
  **N=10**.
- **Confirmation (authoritative):** AlphaVantage `LISTING_STATUS&state=delisted`
  — one cheap call returning a CSV of delisted tickers + delisting dates (not yet
  wired; small client addition in P1). Intersect with the finder:
  - finder-hit **∩ AV-delisted** → deactivate, record `delisted_at` (high conf.)
  - finder-hit **but AV-active** → halt or data-gap → **quarantine, don't
    deactivate** (re-checked next run)

  The intersection is the false-positive guard: frozen-tail alone misfires on
  feed gaps; AV alone is ground truth but you don't want to blind-diff its full
  ~11k-symbol history.

## Action — soft, reversible, auditable

- Set `symbols.active=False` + stamp `delisted_at`, `delisted_source`,
  `swept_at`, `last_traded_date`. Prediction (`active_only=True`) drops them
  immediately; **OHLCV stays in DuckDB** (backfill/history use `active_only=False`,
  so backtests are untouched). This is the existing-but-unused `active` flag.
- **Reactivation pass** (idempotent, bidirectional): if real volume reappears
  (`-u` brings a live bar) or AV relists → flip back to `active=True`. Handles
  relistings and false positives.
- **Protected allowlist:** never deactivate benchmarks/regime ETFs (SPY, QQQ,
  DIA, IWM) even if a feed glitch freezes them.
- Overview refresh = **out of scope** (deferred): `active=False` already
  neutralizes the stale-overview problem upstream of the mcap filter.

## Auditability (per "surfaces must be auditable")

Each run emits a report — candidates found / AV-confirmed deactivations /
quarantined / reactivations — plus a liveness line so "0 swept" is
distinguishable from "sweep broke." `--dry-run` is the default for any mutating
phase (mirrors `bh_swing --manage-dry-run`); flip to live after eyeballing.

## Phasing

| Phase | Deliverable | Size | Status |
|-------|-------------|------|--------|
| **P0** | Frozen-tail finder over DuckDB → candidate CSV + counts, read-only | S | **DONE** |
| **P1** | AV `LISTING_STATUS` client + intersect → confirmed vs quarantined | S–M | proposed |
| **P2** | Soft-deactivate (`active=False` + provenance), `--dry-run`→live | S | proposed |
| **P3** | Reactivation pass + weekly cron + sweep CSV/canary | S–M | proposed |

**Home:** `src/maintenance/delisting_sweep.py`. **Cron (P3):** weekly, Tue–Sat,
after `-u` / before `-p`, registered in `ops/crontab.txt` (with the existing
crontab-drift check). **Est. ~1 day total.**

## P0 usage

```bash
./run.sh python src/bluehorseshoe/maintenance/delisting_sweep.py --min-untraded 10
```

Read-only. Writes `src/logs/delisting_sweep_candidates.csv` and prints a summary
(threshold census, active-candidate count, how many carry a zombie market-cap
that currently passes the mcap filter, protected-symbol exclusions, sample rows).

## Proposed defaults (pending confirmation)

1. **Threshold N = 10** (399 found / 245 active) — vs conservative 20 (347).
2. **Require AV confirmation** before deactivating; quarantine the rest.
3. **Home = `symbols.active` flag only** — `invalid_symbols.txt` is reserved for
   never-valid tickers, not delistings.
