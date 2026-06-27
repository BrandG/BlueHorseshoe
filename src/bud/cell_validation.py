"""Replay-validate v2 cells over FX history — expectancy + exit-geometry sweep.

Two subcommands:

  validate   For each matching cell, replay every fire over full H4 history,
             resolve it to a per-trade R, and report overlap-correct (Newey-West)
             net expectancy plus the BUD A/B/holdout split. This is the standard
             cell gate: a cell PASSES when the net Newey-West CI lower bound > 0
             AND it is positive in interleaved-quarter block A, block B, and the
             last-24-month holdout.

  sweep      The same replay across a TP/SL grid, to find an exit geometry that
             clears the gate (the signal is geometry-independent, so fires are
             found once per pair and re-resolved cheaply per geometry).

What it measures is exactly what the live briefing / auto_trader would have
traded: it calls the live evaluate_cell() for the signal and
compute_entry_stop_target() for the entry + default geometry, and uses the same
warmup window as the briefing (LOOKBACK_BARS).

Resolution model (conservative):
  - limit entry rests at the trigger bar's high (short) / low (long), valid for
    the NEXT bar only — filled iff that bar revisits the level, else no trade.
  - mid entry fills at the trigger-bar close.
  - after fill, scan forward up to --max-hold bars; first bar to touch stop
    (loss, R=-1) or target (win, R=tp/sl) ends it, stop-first on an ambiguous
    bar; otherwise a timeout-exit at the horizon close.
  - a per-trade spread haircut (conservative per-pair pips) gives net R.

    ./run.sh python -m bud.cell_validation validate --strategy ichimoku --direction short
    ./run.sh python -m bud.cell_validation sweep    --strategy ichimoku --direction short
"""
from __future__ import annotations

import argparse
import math
from typing import Optional

import pandas as pd

from bh_ftmo.data.fx_store import FxStore
from bud.briefing import (
    CELLS,
    LOOKBACK_BARS,
    compute_entry_stop_target,
    evaluate_cell,
    ohlc_mid,
)

WARMUP_BARS = LOOKBACK_BARS  # match the live briefing's evaluate window
DEFAULT_MAX_HOLD = 60        # ~10 trading days of H4 bars

# Conservative round-trip spread estimates (pips) for the cost haircut.
# Deliberately pessimistic; refine per pair if real spread data is available.
SPREAD_PIPS = {"GBP_CAD": 3.0, "CAD_CHF": 2.5, "USD_SGD": 3.0}
DEFAULT_SPREAD_PIPS = 3.0

# (tp_pct, sl_pct) exit geometries for the sweep.
GEOMETRY_GRID = [
    (0.010, 0.010), (0.010, 0.0075),
    (0.015, 0.010), (0.015, 0.0075),
    (0.020, 0.010), (0.020, 0.0075), (0.020, 0.0050),
    (0.025, 0.010), (0.025, 0.0125),
    (0.030, 0.010), (0.030, 0.015),
]


def pip_size(pair: str) -> float:
    return 0.01 if pair.endswith("_JPY") else 0.0001


def resolve(mid: pd.DataFrame, i: int, entry: float, stop: float, target: float,
            direction: str, max_hold: int) -> Optional[tuple[float, int]]:
    """Return (gross_R, hold_bars) or None if the limit never filled."""
    n = len(mid)
    short = direction == "short"
    if i + 1 >= n:
        return None
    fb = mid.iloc[i + 1]
    filled = fb["high"] >= entry if short else fb["low"] <= entry
    if not filled:
        return None
    start = i + 1
    risk = abs(stop - entry)
    if risk <= 0:
        return None
    end = min(n, start + max_hold)
    for j in range(start, end):
        b = mid.iloc[j]
        hit_stop = b["high"] >= stop if short else b["low"] <= stop
        hit_tgt = b["low"] <= target if short else b["high"] >= target
        if hit_stop:                       # stop-first on ambiguity (conservative)
            return (-1.0, j - start + 1)
        if hit_tgt:
            r = (entry - target) / risk if short else (target - entry) / risk
            return (r, j - start + 1)
    last = mid.iloc[end - 1]["close"]
    r = (entry - last) / risk if short else (last - entry) / risk
    return (r, end - start)


def find_fires(cell, mid: pd.DataFrame, ts: pd.Series) -> list[tuple]:
    """Walk every bar; return (i, entry, stop, target, entry_ts) for each fire.

    entry/stop/target are the LIVE default geometry from compute_entry_stop_target;
    the sweep keeps `entry` and overrides stop/target from its grid.
    """
    out = []
    for i in range(WARMUP_BARS, len(mid) - 1):
        window = mid.iloc[max(0, i - WARMUP_BARS):i + 1]
        if not evaluate_cell(cell, window):
            continue
        entry, stop, target = compute_entry_stop_target(cell, window)
        out.append((i, entry, stop, target, ts.iloc[i]))
    return out


def newey_west(rs: list[float], lag: int) -> tuple[float, float, float, float]:
    """Bartlett-kernel HAC mean/SE/CI-lo/effective-n for an overlapping series."""
    n = len(rs)
    mean = sum(rs) / n
    d = [x - mean for x in rs]
    g0 = sum(x * x for x in d) / n
    s = g0
    for k in range(1, min(lag, n - 1) + 1):
        w = 1 - k / (lag + 1)
        s += 2 * w * sum(d[t] * d[t + k] for t in range(n - k)) / n
    s = max(s, 1e-12)
    se = math.sqrt(s / n)
    n_eff = n * g0 / s
    return mean, se, mean - 1.96 * se, n_eff


def nw_lag(holds: list[int], n: int, span_bars: float) -> int:
    """Overlap in trade-index units = median hold (bars) x fills-per-bar."""
    fills_per_bar = n / max(span_bars, 1.0)
    med_hold = sorted(holds)[len(holds) // 2]
    return max(1, round(med_hold * fills_per_bar))


def quarter_parity(ts: pd.Timestamp) -> int:
    """Interleaved calendar quarters -> block A (0) / B (1); any regime in both."""
    return (ts.year * 4 + (ts.month - 1) // 3) % 2


def segment_means(records: list[tuple], cutoff: pd.Timestamp) -> tuple:
    """(n,mean) for block A, block B, and the >= cutoff holdout. records=(ts,R)."""
    a = [r for t, r in records if quarter_parity(t) == 0]
    b = [r for t, r in records if quarter_parity(t) == 1]
    h = [r for t, r in records if t >= cutoff]

    def nm(xs):
        return (len(xs), (sum(xs) / len(xs)) if xs else float("nan"))
    return nm(a), nm(b), nm(h)


def _matching_cells(strategy: str, direction: str, pairs: Optional[set]) -> list:
    cells = [c for c in CELLS if c.strategy == strategy and c.direction == direction]
    if pairs:
        cells = [c for c in cells if c.pair in pairs]
    return cells


def run_validate(args) -> int:
    pairs = set(args.pairs.split(",")) if args.pairs else None
    cells = _matching_cells(args.strategy, args.direction, pairs)
    if not cells:
        print("no matching cells")
        return 1
    store = FxStore(read_only=True)
    try:
        for cell in cells:
            df = store.load(cell.pair, granularity="H4", include_incomplete=False)
            if df is None or len(df) < WARMUP_BARS + 10:
                print(f"{cell.pair}: insufficient data")
                continue
            df = df.reset_index(drop=True)
            mid = ohlc_mid(df).reset_index(drop=True)
            ts = pd.to_datetime(df["timestamp"])
            sp = SPREAD_PIPS.get(cell.pair, DEFAULT_SPREAD_PIPS) * pip_size(cell.pair)

            records = []  # (entry_ts, net_R)
            gross, holds = [], []
            for (i, entry, stop, target, ets) in find_fires(cell, mid, ts):
                res = resolve(mid, i, entry, stop, target, cell.direction, args.max_hold)
                if res is None:
                    continue
                r, hold = res
                cost_r = sp / abs(stop - entry)
                gross.append(r)
                holds.append(hold)
                records.append((ets, r - cost_r))
            n = len(records)
            if n < 2:
                print(f"{cell.strategy}:{cell.pair}:{cell.direction}  n={n} (too few)")
                continue

            span = (ts.iloc[-1] - ts.iloc[WARMUP_BARS]).total_seconds() / 3600 / 4
            lag = nw_lag(holds, n, span)
            net = [r for _, r in records]
            g_mean, _, g_cilo, _ = newey_west(gross, lag)
            n_mean, n_se, n_cilo, n_eff = newey_west(net, lag)
            cutoff = ts.iloc[-1] - pd.DateOffset(months=24)
            (nA, mA), (nB, mB), (nH, mH) = segment_means(records, cutoff)
            wins = 100 * sum(1 for x in gross if x > 0) / n

            print(f"\n=== {cell.strategy}:{cell.pair}:{cell.direction} ===")
            print(f"  n={n}  win={wins:.0f}%  NW-lag={lag}  n_eff={n_eff:.0f}")
            print(f"  GROSS mean {g_mean:+.3f}R   NW-CIlo {g_cilo:+.3f}")
            print(f"  NET   mean {n_mean:+.3f}R   NW-SE {n_se:.3f}   NW-CIlo {n_cilo:+.3f}")
            print(f"  split  A n={nA} {mA:+.3f}   B n={nB} {mB:+.3f}   "
                  f"holdout-24mo n={nH} {mH:+.3f}")
            net_gate = n_cilo > 0
            split_gate = mA > 0 and mB > 0 and mH > 0
            verdict = "PASS" if (net_gate and split_gate) else "FAIL"
            print(f"  >>> net-CIlo>0: {net_gate}   A&B&holdout>0: {split_gate}   "
                  f"VERDICT: {verdict}")
    finally:
        store.close()
    return 0


def run_sweep(args) -> int:
    pairs = set(args.pairs.split(",")) if args.pairs else None
    cells = _matching_cells(args.strategy, args.direction, pairs)
    if not cells:
        print("no matching cells")
        return 1
    store = FxStore(read_only=True)
    try:
        for cell in cells:
            df = store.load(cell.pair, granularity="H4", include_incomplete=False)
            if df is None or len(df) < WARMUP_BARS + 10:
                print(f"{cell.pair}: insufficient data")
                continue
            df = df.reset_index(drop=True)
            mid = ohlc_mid(df).reset_index(drop=True)
            ts = pd.to_datetime(df["timestamp"])
            fires = find_fires(cell, mid, ts)  # found once, re-resolved per geometry
            sp = SPREAD_PIPS.get(cell.pair, DEFAULT_SPREAD_PIPS) * pip_size(cell.pair)
            cutoff = ts.iloc[-1] - pd.DateOffset(months=24)

            print(f"\n=== {cell.strategy}:{cell.pair}:{cell.direction} — "
                  f"{len(fires)} fires ===")
            print(f"  {'TP/SL':>11} {'n':>4} {'win%':>5} {'netMean':>8} "
                  f"{'netCIlo':>8} {'A':>7} {'B':>7} {'hold24':>7}  verdict")
            for tp, sl in GEOMETRY_GRID:
                records, gross = [], []
                for (i, entry, _s, _t, ets) in fires:
                    stop = entry * (1 + sl) if cell.direction == "short" else entry * (1 - sl)
                    target = entry * (1 - tp) if cell.direction == "short" else entry * (1 + tp)
                    res = resolve(mid, i, entry, stop, target, cell.direction, args.max_hold)
                    if res is None:
                        continue
                    r, _hold = res
                    records.append((ets, r - sp / (entry * sl)))
                    gross.append(r)
                if len(records) < 5:
                    continue
                net = [r for _, r in records]
                mean, _, cilo, _ = newey_west(net, 1)
                wins = 100 * sum(1 for x in gross if x > 0) / len(net)
                (_, mA), (_, mB), (_, mH) = segment_means(records, cutoff)
                passed = cilo > 0 and mA > 0 and mB > 0 and mH > 0
                print(f"  {tp*100:>4.1f}/{sl*100:<4.2f} {len(net):>4} {wins:>4.0f}% "
                      f"{mean:>+8.3f} {cilo:>+8.3f} {mA:>+7.3f} {mB:>+7.3f} {mH:>+7.3f}"
                      f"{'  *PASS*' if passed else ''}")
    finally:
        store.close()
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Replay-validate v2 cells over FX history")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("validate", run_validate), ("sweep", run_sweep)):
        p = sub.add_parser(name)
        p.add_argument("--strategy", required=True)
        p.add_argument("--direction", required=True, choices=["long", "short"])
        p.add_argument("--pairs", help="comma list; default = all matching cells")
        p.add_argument("--max-hold", type=int, default=DEFAULT_MAX_HOLD, dest="max_hold")
        p.set_defaults(func=fn)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
