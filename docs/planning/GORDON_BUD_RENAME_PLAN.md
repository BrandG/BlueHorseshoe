# Gordon / Bud Rename Plan

**Status:** DRAFT — not executed. Document-only output of the 2026-05-27 naming
session. See [`../PROJECTS.md`](../PROJECTS.md) for the naming itself.

**Goal:** make the on-disk layout match the two-product mental model (GORDON =
equities, BUD = forex/FTMO) so the `src/` jumble stops being confusing.

**Guiding principle:** *clarity per unit of risk.* This is a **live** system —
crons fire every 5 min (swing monitor) and every 4 h (Bud traders submit real
OANDA orders). We rename the things a human reads and types (entry scripts,
wrappers, crons) and we **do not** rename the things that would ripple through
hundreds of imports or touch live state, unless the payoff clearly justifies it.

---

## Blast radius (measured 2026-05-27)

| Rename target | Files affected | Extra hazards | Verdict |
|---|---|---|---|
| `bluehorseshoe/` package | **146** import it | systemd unit `uvicorn bluehorseshoe.api.main:app`; ProcessPool pickles by module path | **Defer** |
| `bh_ftmo/` package | **104** import it | ProcessPool pickling of strategies; `python -m bh_ftmo.predict` in cron | **Defer** |
| `bh_swing/` package | **20** import it | client_id wiring, journal paths | **Defer** |
| Entry-point scripts (`src/bh_*.py`) | ~6 cross-imports + 5 wrappers + cron | live crons | **Tier 1 (do this)** |
| `run_*.sh` wrappers | crontab only | live crons | **Tier 1** |
| Config/state JSON (`bh_lite_*.json`, `bh_ftmo_config.json`) | 5 code refs; **live position state** | losing open-position tracking | **Tier 3 (migrate carefully)** |
| Log/journal CSV filenames | cron redirects + code | breaks history continuity | **Don't (keep names)** |

---

## What we will NOT rename (and why)

1. **The Python packages** (`bluehorseshoe/`, `bh_ftmo/`, `bh_swing/`).
   146 + 104 + 20 import sites, the systemd API service, and (critically)
   `ProcessPoolExecutor` workers that import by module path. The clarity payoff
   is small — nobody *types* a package name — and the failure modes are silent
   (a pickling import error inside a worker, an API service that won't boot).
   Instead, **Tier 2** adds a one-line product banner to each package's
   `__init__.py` docstring (`"""GORDON · Engine — …"""`). Zero risk, full clarity
   at the place you'd look.

2. **Log / journal filenames** (`bh_swing_journal.csv`, `bh_ftmo_paper_journal.csv`,
   …). These are append-only history. Renaming orphans months of data and buys
   nothing — the *folder* (`src/logs/`) is already the index. Keep as-is.

3. **Live config/state files** during Tier 1. `bh_lite_positions.json` holds the
   open FTMO challenge positions; `bh_ftmo_config.json` is read every 4 h. These
   move only in **Tier 3**, with a synchronized code+data migration and a quiet
   window (see below).

---

## Target layout (the destination)

Entry scripts and wrappers grouped by product. Packages stay where they are
(banner-documented, not moved). `main.py` stays put — it's THE Gordon CLI.

```
src/
├── main.py                       GORDON · Engine CLI            (unchanged)
├── bluehorseshoe/                GORDON · Engine package        (unchanged; banner)
├── bh_swing/                     GORDON · Manager package       (unchanged; banner)
├── bh_ftmo/                      BUD · Lab package              (unchanged; banner)
│
├── gordon/                       ← NEW folder: equities entry scripts
│   ├── swing_monitor.py          (← bh_swing_monitor.py)
│   ├── swing_status.py           (← bh_swing_status.py)
│   ├── swing_flatten.py          (← bh_swing_flatten.py)
│   ├── swing_friday_flatten.py   (← bh_swing_friday_flatten.py)
│   ├── swing_diagnose.py         (← bh_swing_diagnose.py)
│   └── swing_review.py           (← bh_swing_review.py)
│
└── bud/                          ← NEW folder: forex entry scripts
    ├── auto_rising3bar.py        (← bh_ftmo_paper.py)
    ├── auto_v2.py                (← bh_ftmo_v2_paper.py)
    ├── flatten.py                (← bh_ftmo_flatten.py)
    ├── status.py                 (← bh_ftmo_status.py)
    ├── briefing.py               (← bh_briefing.py)
    ├── briefing_ftmo.py          (← bh_briefing_ftmo.py)
    └── envelope.py               (← ftmo_envelope.py)
```

> **DECIDED 2026-05-27:** use the descriptive `swing_*` / `auto_*` stems shown
> above (not the bare `gordon/monitor.py` form) — they read better cold.

`src/bh_live_*.py` (Gateway keepalive/status) and the IBKR watchdog wrappers are
**cross-cutting infra** — they stay at the top level (documented as such).
`bh_positions.py` reads `bh_lite_*.json`; classify it as Bud and move it with the
config in Tier 3, or move now and leave the config path absolute.

---

## Tier 1 — entry scripts + wrappers + crons (✅ SHIPPED 2026-05-30)

**Phase A** (Gordon swing scripts → `src/gordon/`): commit `bac129b`.
**Phase B** (Bud forex scripts → `src/bud/`): see commit log on master.

Two follow-ups originally scoped *out* of Tier 1:
- `src/bh_ftmo_trader.py` — newer unified autonomous trader. **Moved to
  `src/bud/auto_trader.py` in a follow-up commit shortly after Phase B**
  (descriptive `auto_*` stem, matches the legacy `auto_rising3bar.py` /
  `auto_v2.py` siblings).
- `src/bh_positions.py` — kept here pending Tier 3 (config-envelope rename).


Delivers ~80% of the clarity at low, contained risk. Do GORDON and BUD as two
separate atomic changes so a mistake only ever endangers one product.

### Per-product steps (repeat for gordon/, then bud/)

1. `git mv` each script into the new folder. Add `src/<product>/__init__.py`.
2. **Fix cross-imports** (the only non-mechanical part):
   - `bud/briefing_ftmo.py`: `from bh_briefing import …` → `from bud.briefing import …`;
     `from ftmo_envelope import …` → `from bud.envelope import …`
   - `bud/auto_v2.py`: `from bh_briefing import …` → `from bud.briefing import …`;
     `from bh_ftmo_paper import …` → `from bud.auto_rising3bar import …`
   - (GORDON swing scripts have no script-to-script cross-imports — only
     `from bh_swing… import`, which is the *package* and is unchanged.)
3. **Update the `run_*.sh` wrappers** to point at the new paths
   (`src/bh_briefing.py` → `src/bud/briefing.py`, etc.). Wrappers are the
   indirection layer cron uses — most cron lines need no edit.
4. **Update the two *inline* cron lines** that bypass wrappers:
   `./run.sh python src/bh_ftmo_paper.py` → `…src/bud/auto_rising3bar.py`.
   (The `-m bh_ftmo.predict` and `-m bh_ftmo.data.incremental_update` lines are
   package calls — untouched in Tier 1.)
5. **Update test imports** that reference the moved scripts
   (`src/tests/test_bh_briefing_ftmo.py`, `test_ftmo_envelope.py`).
6. Run `./run.sh pytest` + `./run.sh ./lint.sh` green before touching cron.

### Live-system coordination (quiet windows)

- **BUD crons** fire at minutes 05–30 of UTC hours 01,05,09,13,17,21, plus a
  22:30 weekday brief. Land Bud changes **between** cycles (e.g. UTC 02:00–04:30).
- **GORDON swing monitor** fires every 5 min, 13:00–21:00 UTC, Mon–Fri. Either
  land outside that window, or pause it first with the kill-switch:
  `touch /root/BlueHorseshoe/.bh_swing_pause_management` (remove after verify).
- Sequence: land code commit → update `crontab` → wait for the next scheduled
  tick → confirm the new path ran (tail the wrapper's log).

### Verification

- `pytest` + `lint` green.
- Manual smoke each moved entry point with `--dry-run` where supported
  (`./run.sh python src/bud/auto_v2.py --dry-run`).
- After the next live tick, the corresponding `src/logs/*.log` shows a clean run
  from the new path (no `ModuleNotFoundError`, no missing-file).

### Rollback

Each product is one commit + one crontab edit. Rollback = `git revert <sha>` +
restore the crontab block from `crontab -l` backup taken before the change.
Because `git mv` preserves history, reverting is clean.

---

## Tier 2 — package docstring banners (✅ DONE 2026-05-27, zero risk)

Product line prepended to each package's top-level docstring so the boundary is
obvious at the place an engineer actually opens:

- `src/bluehorseshoe/__init__.py` → `GORDON · Engine` (was empty)
- `src/bh_swing/__init__.py` → `GORDON · Manager`
- `src/bh_ftmo/__init__.py` → `BUD · Lab`

No imports changed.

---

## Tier 3 — config/state file rename (OPTIONAL, higher care)

Only if the `bh_lite_*.json` names still grate after Tiers 1–2. These hold live
state, so:

1. Pick a quiet window (no Bud cron for ≥30 min; ideally weekend).
2. `git mv bh_lite_config.json bud/config.json` etc. **and** update the 5 code
   refs (`bud/positions.py`, `bud/briefing_ftmo.py`, `bud/envelope.py`, 2 tests)
   in the *same* commit.
3. Confirm `bh_lite_positions.json` content (open positions) carried over intact
   — diff before/after.
4. Verify the next brief reads the right open positions before trusting it.

Defer indefinitely unless the payoff is felt; this is the lowest clarity-per-risk
of all the tiers.

---

## Recommended path

**Do Tier 2 now (free), schedule Tier 1 for a quiet window, defer Tier 3.**
Leave the Python packages named as they are — the docstring banner + `PROJECTS.md`
give the clarity without the 146-import refactor or the pickling/systemd risk.

When ready to execute Tier 1, this hands off cleanly to Codex: fresh branch from
`master`, one commit per product, crontab edit applied by hand in the quiet
window (Codex can't safely edit a live crontab).
