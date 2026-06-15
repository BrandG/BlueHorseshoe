"""Observability for the BUD FTMO briefing — make a zero-order run auditable.

The briefing's default output collapses the whole decision into one line
("No tradeable fires on this bar"), which renders three very different states
identically: a quiet market (0 cells fired), a working filter (fires fired but
all suppressed), and a broken pipeline (bars failed to load). This module
exposes the machinery so those are distinguishable.

Two public pieces:

* :class:`FunnelTrace` / :func:`render_funnel_trace` — the per-stage candidate
  count with the ``skip_reason`` for every dropped fire. Answers "where did the
  candidates die?" for any given bar.
* :func:`record_fire_event` / :func:`read_liveness` / :func:`render_liveness` —
  an append-only, one-row-per-bar fire log plus a trailing-window reader, so a
  "0 fires" outcome is judged against the normal fire rate ("last fire 2 days
  ago; 18 fire-events in the trailing 30d") rather than taken on faith.

Nothing here mutates trading state; it only reads bars and writes a CSV log.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timedelta, UTC
from pathlib import Path
from typing import Optional

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
FIRE_HISTORY_PATH = REPO_ROOT / "src" / "logs" / "bud_fire_history.csv"
FIRE_HISTORY_FIELDS = ("bar_ts", "run_utc", "cells_evaluated", "cells_fired", "accepted")


# --------------------------------------------------------------------------- #
# Funnel trace
# --------------------------------------------------------------------------- #
@dataclass
class FunnelTrace:
    """Per-stage candidate counts for one briefing bar.

    ``fires_raw``/``pos_skipped``/``cluster_suppressed``/``capped``/``accepted``
    are the actual fire dicts (each carrying ``pair``/``direction`` and, for the
    dropped ones, a ``skip_reason``), so the renderer can name every casualty.
    """
    bar_ts: Optional[pd.Timestamp]
    cells_defined: int
    pairs_total: int
    pairs_loaded: int
    starved_pairs: list[str] = field(default_factory=list)
    fires_raw: list[dict] = field(default_factory=list)
    pos_skipped: list[dict] = field(default_factory=list)
    cluster_suppressed: list[dict] = field(default_factory=list)
    capped: list[dict] = field(default_factory=list)
    accepted: list[dict] = field(default_factory=list)
    slots_left: int = 0
    daily_room: float = 0.0


def _fire_label(f: dict) -> str:
    return f"{f.get('pair', '?'):<8} {f.get('direction', '?'):<5}"


def render_funnel_trace(t: FunnelTrace) -> str:
    """Render a :class:`FunnelTrace` as a fixed-width, stage-by-stage block."""
    W = 64
    out: list[str] = []
    out.append("=" * W)
    out.append("FUNNEL TRACE — where every candidate went")
    out.append(f"  last closed H4 bar : {t.bar_ts}")
    out.append("=" * W)

    out.append(f"[1] cells defined            : {t.cells_defined} across {t.pairs_total} pairs")
    starved = (f"   STARVED: {t.starved_pairs}" if t.starved_pairs
               else "   (all pairs have data)")
    out.append(f"[2] pairs with H4 data       : {t.pairs_loaded}/{t.pairs_total}{starved}")

    out.append(f"[3] cells fired on this bar  : {len(t.fires_raw)}")
    for f in t.fires_raw:
        out.append(f"        FIRE  {_fire_label(f)} {f.get('strategy', ''):<22}"
                   f" d1={f.get('d1_align', '?')}")
    if not t.fires_raw:
        out.append("        (no cell's entry condition triggered on the last closed bar)")

    def _stage(num: int, name: str, dropped: list[dict]) -> None:
        out.append(f"[{num}] {name:<24} : -{len(dropped)}")
        for f in dropped:
            out.append(f"        DROP  {_fire_label(f)} {f.get('skip_reason', '')}")

    _stage(4, "held-pair skip", t.pos_skipped)
    _stage(5, "cluster suppression", t.cluster_suppressed)
    out.append(f"[6] slot/risk cap            : -{len(t.capped)}  "
               f"(slots left={t.slots_left}, daily room=${t.daily_room:,.0f})")
    for f in t.capped:
        out.append(f"        DROP  {_fire_label(f)} {f.get('skip_reason', '')}")

    out.append("-" * W)
    out.append(f"[=] ACCEPTED ORDERS          : {len(t.accepted)}")
    for f in t.accepted:
        lots = f.get("lots", "?")
        out.append(f"        ORDER {_fire_label(f)} {lots} lots")
    out.append("=" * W)
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Fire-rate liveness
# --------------------------------------------------------------------------- #
def record_fire_event(
    bar_ts: pd.Timestamp,
    cells_evaluated: int,
    cells_fired: int,
    accepted: int,
    *,
    now_utc: Optional[datetime] = None,
    path: Path = FIRE_HISTORY_PATH,
) -> None:
    """Upsert one row (keyed by ``bar_ts``) into the append-only fire log.

    Keyed by bar so re-running the briefing on the same H4 bar overwrites rather
    than double-counts. O(file) per call — the file is one row per H4 bar, tiny.
    """
    now_utc = now_utc or datetime.now(UTC)
    key = str(bar_ts)
    rows: dict[str, dict] = {}
    if path.exists():
        with path.open(newline="") as fh:
            for r in csv.DictReader(fh):
                rows[r["bar_ts"]] = r
    rows[key] = {
        "bar_ts": key,
        "run_utc": now_utc.isoformat(),
        "cells_evaluated": str(cells_evaluated),
        "cells_fired": str(cells_fired),
        "accepted": str(accepted),
    }
    ordered = sorted(rows.values(), key=lambda r: r["bar_ts"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIRE_HISTORY_FIELDS)
        w.writeheader()
        w.writerows(ordered)


@dataclass
class Liveness:
    window_days: int
    bars_logged: int           # rows in the trailing window
    fire_events: int           # sum of cells_fired in the window
    bars_with_fire: int        # rows with cells_fired > 0
    last_fire_bar: Optional[str]
    last_fire_age_days: Optional[float]
    history_exists: bool


def read_liveness(
    window_days: int = 30,
    *,
    now_utc: Optional[datetime] = None,
    path: Path = FIRE_HISTORY_PATH,
) -> Liveness:
    """Summarise fire activity over the trailing ``window_days`` from the log."""
    now_utc = now_utc or datetime.now(UTC)
    if not path.exists():
        return Liveness(window_days, 0, 0, 0, None, None, history_exists=False)

    cutoff = now_utc - timedelta(days=window_days)
    bars_logged = fire_events = bars_with_fire = 0
    last_fire_bar: Optional[str] = None
    with path.open(newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                bar_dt = pd.Timestamp(r["bar_ts"]).to_pydatetime()
            except (ValueError, KeyError):
                continue
            if bar_dt.tzinfo is None:
                bar_dt = bar_dt.replace(tzinfo=UTC)
            fired = int(r.get("cells_fired", 0) or 0)
            # last_fire scans the whole log so "last fire" survives a stale window
            if fired > 0 and (last_fire_bar is None or r["bar_ts"] > last_fire_bar):
                last_fire_bar = r["bar_ts"]
            if bar_dt < cutoff:
                continue
            bars_logged += 1
            fire_events += fired
            bars_with_fire += 1 if fired > 0 else 0

    age = None
    if last_fire_bar is not None:
        lf = pd.Timestamp(last_fire_bar).to_pydatetime()
        if lf.tzinfo is None:
            lf = lf.replace(tzinfo=UTC)
        age = (now_utc - lf).total_seconds() / 86400.0
    return Liveness(window_days, bars_logged, fire_events, bars_with_fire,
                    last_fire_bar, age, history_exists=True)


def render_liveness(lv: Liveness) -> str:
    """One-line liveness summary for the console/email header."""
    if not lv.history_exists or lv.bars_logged == 0:
        return ("LIVENESS: no fire history yet — base rate builds as the briefing "
                "runs (and the one-time seed populates it).")
    if lv.last_fire_age_days is None:
        last = "never (in log)"
    else:
        last = f"{lv.last_fire_age_days:.1f}d ago ({lv.last_fire_bar})"
    return (f"LIVENESS: {lv.fire_events} fire-events on {lv.bars_with_fire}/"
            f"{lv.bars_logged} bars in trailing {lv.window_days}d — last fire {last}")
