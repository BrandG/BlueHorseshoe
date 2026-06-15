"""One-time offline seed for the BUD fire-history log (bud_fire_history.csv).

Replays the current cell set over the last ``--window`` H4 bars and writes one
row per bar with the count of cells that fired, so :func:`bud.diagnostics.
read_liveness` has a real base rate from day one instead of bootstrapping from
empty. EXPENSIVE (~minutes): evaluate_cell recompute is ~55ms/call and this is
cells x bars calls. Run manually, off the cron path. Idempotent — re-running
upserts the same bar_ts rows.

    ./run.sh python -m bud.seed_fire_history --window 180
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict

import pandas as pd

from bh_ftmo.data.fx_store import FxStore
from bud.briefing import CELLS, evaluate_cell, ohlc_mid
from bud.diagnostics import FIRE_HISTORY_FIELDS, FIRE_HISTORY_PATH

WARMUP_BARS = 300  # match the live briefing's tail(LOOKBACK_BARS) warmup budget


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Seed bud_fire_history.csv via cell replay")
    ap.add_argument("--window", type=int, default=180,
                    help="number of trailing H4 bars to replay (default 180 ~= 30 trading days)")
    args = ap.parse_args(argv)

    store = FxStore(read_only=True)
    mids: dict[str, pd.DataFrame] = {}
    tss: dict[str, pd.Series] = {}
    try:
        for pair in {c.pair for c in CELLS}:
            df = store.load(pair, granularity="H4", include_incomplete=False)
            if df is not None and len(df) >= 60:
                mids[pair] = ohlc_mid(df).reset_index(drop=True)
                tss[pair] = df["timestamp"].reset_index(drop=True)
    finally:
        store.close()

    fired_by_bar: dict[pd.Timestamp, int] = defaultdict(int)
    evaluated_by_bar: dict[pd.Timestamp, int] = defaultdict(int)
    total_calls = 0
    for cell in CELLS:
        mid = mids.get(cell.pair)
        if mid is None or len(mid) < 60:
            continue
        ts = tss[cell.pair]
        end = len(mid)
        start = max(WARMUP_BARS, end - args.window)
        for i in range(start, end):
            bar_ts = pd.Timestamp(ts.iloc[i])
            evaluated_by_bar[bar_ts] += 1
            total_calls += 1
            if evaluate_cell(cell, mid.iloc[max(0, i - WARMUP_BARS):i + 1]):
                fired_by_bar[bar_ts] += 1

    # Merge with any existing log (upsert by bar_ts), preserving forward rows.
    rows: dict[str, dict] = {}
    if FIRE_HISTORY_PATH.exists():
        with FIRE_HISTORY_PATH.open(newline="") as fh:
            for r in csv.DictReader(fh):
                rows[r["bar_ts"]] = r
    for bar_ts in sorted(evaluated_by_bar):
        key = str(bar_ts)
        rows[key] = {
            "bar_ts": key,
            "run_utc": rows.get(key, {}).get("run_utc", "seed"),
            "cells_evaluated": str(evaluated_by_bar[bar_ts]),
            "cells_fired": str(fired_by_bar.get(bar_ts, 0)),
            "accepted": rows.get(key, {}).get("accepted", ""),
        }

    ordered = sorted(rows.values(), key=lambda r: r["bar_ts"])
    FIRE_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with FIRE_HISTORY_PATH.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIRE_HISTORY_FIELDS)
        w.writeheader()
        w.writerows(ordered)

    bars = len(evaluated_by_bar)
    fires = sum(fired_by_bar.values())
    print(f"seeded {bars} bars, {fires} fire-events ({total_calls} evals) "
          f"→ {FIRE_HISTORY_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
