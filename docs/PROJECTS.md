# BlueHorseshoe — Project Map

**This is the canonical "what are these projects" doc.** It names the
subsystems and draws the boundaries between them. For *how to run* each one
(every flag, every cron line), see [`SUBSYSTEMS_GUIDE.md`](SUBSYSTEMS_GUIDE.md).

BlueHorseshoe started as a single US-equity prediction engine and grew into
**two distinct trading products** across two asset classes and two brokers.
We name the two products after *Wall Street* (1987) — the parent repo is named
for Gekko's "Blue Horseshoe loves Anacott Steel" tip:

- **GORDON** — the US-equities product (the original; Gekko, the established operator).
- **BUD** — the forex / FTMO product (the protégé chasing a *funded* account).

```
BlueHorseshoe (umbrella repo)
│
├── GORDON  — US equities, via IBKR
│   ├── Engine    signal + prediction        src/bluehorseshoe/  + src/main.py
│   └── Manager   post-fill position mgmt     src/bh_swing/
│
└── BUD     — forex, via OANDA (toward FTMO funding)
    ├── Lab        research + backtest        src/bh_ftmo/
    ├── Auto       autonomous paper traders   src/bh_ftmo_paper.py, src/bh_ftmo_v2_paper.py
    ├── Briefing   human-in-loop signals      src/bh_briefing.py, src/bh_briefing_ftmo.py
    └── Envelope   shared config/state        src/bh_lite_*.json   (engine retired; config kept)
```

The two products are deliberately **not** co-mingled in code: `bluehorseshoe/`
and `bh_swing/` are GORDON; `bh_ftmo/` and the `bh_briefing*` / `bh_ftmo_*`
scripts are BUD. They share only the repo, the venv (`run.sh`), MongoDB, and
the cron host.

---

## GORDON — US Equities (IBKR)

One product in two halves: **open** positions, then **manage** them.

### Gordon · Engine — signal & prediction *(the original)*

- **Code:** `src/bluehorseshoe/` (~25k LOC) + `src/main.py` CLI
- **Does:** ingests OHLCV → DuckDB, scores ~11k NASDAQ stocks on Baseline
  (trend) and Mean Reversion, adds ML win-prob / stop-loss overlays, writes an
  HTML report, and — if `PAPER_TRADING_ENABLED=true` — submits 3-leg bracket
  orders to the IBKR **paper** account (`PaperTrader`, client_id=1).
- **Runs:** `run_daily_pipeline.sh` @ 01:00 Tue–Sat; weekly retrain Sun 02:00.
- **Status:** Production. This is the foundation everything else grew out of.

### Gordon · Manager — post-fill management *(your "bh swing")*

- **Code:** `src/bh_swing/` (~1.7k LOC) + `bh_swing_monitor.py` (entrypoint),
  `bh_swing_status.py`, `bh_swing_flatten.py`, `bh_swing_friday_flatten.py`
- **Does:** picks up the bracket orders the Engine placed and walks each
  position through its lifecycle — reconciles fills into the journal, advances
  T2 stops to breakeven once T1 fills, Friday-flattens. **Not its own trading
  universe** — it babysits Gordon · Engine's IBKR positions. (client_id=7)
- **Runs:** every 5 min during US hours, `--manage-dry-run` (Phase 1a shadow);
  Friday flatten @ 19:55. Live `--manage` not yet promoted.
- **Status:** Active dev (Phase 1a). Plan: `synthetic-cooking-meerkat`.

**The relationship:** Engine opens → Manager manages. Same broker (IBKR paper),
same instruments (the journal's NVGS/TRP/RPRX/NTAP… are exactly these
positions). Live-account readiness is the long-term goal.

---

## BUD — Forex / FTMO (OANDA)

The forex venture: trade an OANDA practice account well enough to pass an FTMO
challenge and earn a *funded* account. Three live channels plus a research lab,
all on the **H4** timeframe.

### Bud · Lab — research & backtest

- **Code:** `src/bh_ftmo/` (~11k LOC) — the FTMO-native scoring/backtest engine
  (`predict.py`, `backtest/`, `indicators/`, `research/`). Distinct from
  Gordon's equity scorer (per the 2026-05-27 scoring split).
- **Does:** strategy research, walk-forward validation, and the
  `bh_ftmo.predict` signal-emission CLI. The shape every Bud strategy is
  validated through before it goes live.
- **Runs:** `bh_ftmo.data.incremental_update` + `bh_ftmo.predict` on each H4
  close (cron). Heavy research is manual / on the research droplet.

### Bud · Auto — autonomous paper traders

- **Code:** `src/bh_ftmo_paper.py` and `src/bh_ftmo_v2_paper.py`
- **Does:** fully closed-loop OANDA paper trading — detect signal → safety
  gates → submit OANDA order → journal → close on TP/SL/age. **Two traders:**
  - `bh_ftmo_paper` — rising_3bar, 1.5%/1.5%, all 40 H4 pairs (live 2026-04-30)
  - `bh_ftmo_v2_paper` — 33 cells / 9 strategies / 17 pairs, 0.5% risk
- **Operator tools:** `bh_ftmo_flatten.py`, `bh_ftmo_status.py`
- **Runs:** every 4h on H4 closes (UTC 01,05,09,13,17,21).
- **Status:** Live on OANDA demo.

### Bud · Briefing — human-in-the-loop signals *(supersedes bh_lite)*

- **Code:** `src/bh_briefing.py` + `src/bh_briefing_ftmo.py`
- **Does:** emails the firing H4 cells as **sized, placeable FTMO orders** with
  position-health on open trades — you read it and place trades manually. The
  human counterpart to Bud · Auto.
- **Runs:** each H4 close (after the Auto traders) + a 22:30 weekday brief.
- **Status:** Production. **This is what replaced bh_lite** as the human-driven
  channel.

### Bud · Envelope — shared config/state *(bh_lite, retired engine)*

- **Code:** `src/bh_lite_*.json` only. The `bh_lite` *engine* is retired
  (dormant since 2026-05-12; see [`planning/BH_LITE_SUNDOWN.md`](planning/BH_LITE_SUNDOWN.md)).
- **Why it still matters:** `bh_lite_config.json` (account, risk, instruments,
  12 clusters) and `bh_lite_positions.json` are **still load-bearing** — read
  by `bh_briefing_ftmo` and `ftmo_envelope` to keep the FTMO trading envelope
  consistent. **Do not delete these files** even though the engine is gone.

---

## Cross-cutting infrastructure (belongs to neither product)

- **IB Gateway watchdog / keepalive / restart** (`run_ibgw_*.sh`) — keeps the
  IBKR Gateway container healthy for GORDON.
- **MongoDB** — scores, journal, overviews (GORDON); some Bud config/state.
- **DuckDB** (`data/ohlcv.duckdb`) — GORDON's OHLCV store.
- **Backup** (`backup.sh`), **venv wrapper** (`run.sh`).

---

## At a glance

| Product | Sub | Asset / broker | Automation | Status |
|---|---|---|---|---|
| GORDON | Engine | US equities / IBKR | Signal generation | Production |
| GORDON | Manager | US equities / IBKR | Auto post-fill mgmt | Phase 1a (dev) |
| BUD | Lab | Forex / — | Research | Production |
| BUD | Auto | Forex / OANDA | Fully autonomous | Live (demo) |
| BUD | Briefing | Forex / OANDA→FTMO | Human-in-the-loop | Production |
| BUD | Envelope | Forex / — | Config only | Retired engine |
