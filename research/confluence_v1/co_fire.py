"""P0 addendum: strict-AND co-fire feasibility for the confluence sweep.

Fire-mask CORRELATION (factor_grouping.py) answers "do triggers coincide?" but
not "are there enough simultaneous same-direction fires to TEST a strict-AND
BOTH cell?". This script answers the latter — the number that actually gates P1.

For each deployed forex pair, it builds DIRECTION-AWARE fresh fire masks (long
and short separately) for all 10 evaluators, reusing the exact trigger logic and
modal deployed params from factor_grouping.py. Then, per
(forex_pair, direction, evaluator_A, evaluator_B), it counts bars where both
fire. Each such bar is one candidate BOTH trade, so the count is directly
comparable to an n-floor (~40 trades over ~11 years).

Read: if no (forex_pair, direction) cell reaches the n-floor for a given
evaluator pair, that pair is UNTESTABLE under strict-AND — sparsity, not
redundancy, is the binding constraint.
"""
from __future__ import annotations

import sys
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from factor_grouping import (  # noqa: E402  (path-injected sibling module)
    EVALUATORS,
    _fresh_mask,
    choose_params,
    deployed_cells,
)
from bh_ftmo.data.fx_store import FxStore  # noqa: E402
from bh_ftmo.indicators import (  # noqa: E402
    atr,
    bollinger_bands,
    cci,
    ema,
    ichimoku,
    is_bullish_engulfing,
    macd,
    ohlc_mid,
    rsi,
    sma,
    stochastic,
)

N_FLOOR = 40


def _osc_dir(arr, *, threshold, recovery, signed):
    n = len(arr)
    long_cond = np.zeros(n, dtype=bool)
    short_cond = np.zeros(n, dtype=bool)
    if n < recovery + 2:
        return _fresh_mask(long_cond), _fresh_mask(short_cond)
    if signed:
        long_base, short_base = -threshold, threshold
    else:
        long_base, short_base = threshold, 100.0 - threshold
    finite = np.isfinite(arr)
    for idx in range(recovery, n):
        if not finite[idx] or not finite[idx - recovery]:
            continue
        long_consec = all(arr[idx - i] > arr[idx - i - 1] for i in range(recovery))
        short_consec = all(arr[idx - i] < arr[idx - i - 1] for i in range(recovery))
        long_cond[idx] = long_consec and arr[idx - recovery] < long_base
        short_cond[idx] = short_consec and arr[idx - recovery] > short_base
    return _fresh_mask(long_cond), _fresh_mask(short_cond)


def _stoch_dir(mid, p):
    s = stochastic(mid, k_period=p["k_period"], d_period=p["d_period"])
    return _osc_dir(s["k"].to_numpy(float), threshold=float(p["threshold"]),
                    recovery=int(p["recovery"]), signed=False)


def _rsi_dir(mid, p):
    return _osc_dir(rsi(mid, period=p["period"]).to_numpy(float),
                    threshold=float(p["threshold"]), recovery=int(p["recovery"]), signed=False)


def _cci_dir(mid, p):
    return _osc_dir(cci(mid, period=p["period"]).to_numpy(float),
                    threshold=float(p["threshold"]), recovery=int(p["recovery"]), signed=True)


def _bb_dir(mid, p):
    b = bollinger_bands(mid, period=p["period"], n_std=p["n_std"])
    close = mid["close"].to_numpy(float)
    lower = b["lower"].to_numpy(float)
    upper = b["upper"].to_numpy(float)
    width = upper - lower
    depth = float(p["depth"])
    return _fresh_mask(close < (lower - depth * width)), _fresh_mask(close > (upper + depth * width))


def _macd_dir(mid, p):
    f = macd(mid, fast=p["fast"], slow=p["slow"], signal=p["signal"])
    m = f["macd"].to_numpy(float)
    sig = f["signal"].to_numpy(float)
    if p["trigger"] == "signal_cross":
        return _fresh_mask(m > sig), _fresh_mask(m < sig)
    if p["trigger"] == "zero_cross":
        return _fresh_mask(m > 0.0), _fresh_mask(m < 0.0)
    raise ValueError(p["trigger"])


def _ma_dir(mid, p, ma_fn):
    ma = ma_fn(mid, period=p["period"]).to_numpy(float)
    band = float(p["k"]) * atr(mid, period=p["atr_period"]).to_numpy(float)
    close = mid["close"].to_numpy(float)
    return _fresh_mask(close < ma - band), _fresh_mask(close > ma + band)


def _atr_dir(mid, p):
    open_a = mid["open"].to_numpy(float)
    high = mid["high"].to_numpy(float)
    low = mid["low"].to_numpy(float)
    close = mid["close"].to_numpy(float)
    k = float(p["k"])
    if p["trigger"] == "close_breakout":
        a = atr(mid, period=p["atr_period"]).to_numpy(float)
        lc = close > np.roll(close, 1) + k * np.roll(a, 1)
        sc = close < np.roll(close, 1) - k * np.roll(a, 1)
        lc[0] = sc[0] = False
        return _fresh_mask(lc), _fresh_mask(sc)
    if p["trigger"] != "range_expansion":
        raise ValueError(p["trigger"])
    lookback = int(p.get("range_lookback", 14))
    rng = high - low
    mean_rng = pd.Series(rng).rolling(lookback, min_periods=lookback).mean().to_numpy()
    prior = np.roll(mean_rng, 1)
    prior[0] = np.nan
    big = rng > k * prior
    return _fresh_mask(big & (close > open_a)), _fresh_mask(big & (close < open_a))


def _ichimoku_dir(mid, p):
    f = ichimoku(mid, tenkan_period=p["tenkan"], kijun_period=p["kijun"],
                 senkou_b_period=p["senkou_b"], displacement=p["displacement"])
    if p["trigger"] != "tk_cross":
        raise ValueError(p["trigger"])
    tk = f["tenkan"].to_numpy(float)
    kj = f["kijun"].to_numpy(float)
    return _fresh_mask(tk > kj), _fresh_mask(tk < kj)


def _candle_dir(mid, p):
    if p["pattern"] != "bull_engulf":
        raise ValueError(p["pattern"])
    kwargs = {"min_body_frac": 0.5} if bool(p.get("strict", False)) else {}
    long_mask = is_bullish_engulfing(mid, **kwargs).to_numpy(bool)
    return long_mask, np.zeros(len(long_mask), dtype=bool)  # bullish pattern: long only


def _sma_dir(mid, p):
    return _ma_dir(mid, p, sma)


def _ema_dir(mid, p):
    return _ma_dir(mid, p, ema)


DIR_MASKERS = {
    "atr": _atr_dir, "bb": _bb_dir, "candle": _candle_dir, "cci": _cci_dir,
    "ema": _ema_dir, "ichimoku": _ichimoku_dir, "macd": _macd_dir,
    "rsi": _rsi_dir, "sma": _sma_dir, "stoch": _stoch_dir,
}


def main() -> None:
    cells = deployed_cells()
    pairs = sorted({c.pair for c in cells})
    choices = choose_params(cells)

    # masks_by_pair[pair][evaluator] = {"long": fresh_bool, "short": fresh_bool}
    masks_by_pair = {}
    solo = {e: {"long": 0, "short": 0} for e in EVALUATORS}
    with FxStore(read_only=True) as store:
        for pair in pairs:
            mid = ohlc_mid(store.load(pair, granularity="H4", include_incomplete=False))
            d = {}
            for e in EVALUATORS:
                lo, sh = DIR_MASKERS[e](mid, choices[e].params)
                d[e] = {"long": lo.astype(bool), "short": sh.astype(bool)}
                solo[e]["long"] += int(lo.sum())
                solo[e]["short"] += int(sh.sum())
            masks_by_pair[pair] = d

    rows = []
    for a, b in combinations(EVALUATORS, 2):
        for direction in ("long", "short"):
            counts = {p: int((masks_by_pair[p][a][direction] & masks_by_pair[p][b][direction]).sum())
                      for p in pairs}
            total = sum(counts.values())
            mx = max(counts.values()) if counts else 0
            testable_cells = sum(1 for v in counts.values() if v >= N_FLOOR)
            rows.append({"a": a, "b": b, "direction": direction, "total_cofire": total,
                         "max_pair_cofire": mx, "testable_pair_cells": testable_cells})
    df = pd.DataFrame(rows)
    out_csv = Path(__file__).resolve().parent / "co_fire_counts.csv"
    df.sort_values("max_pair_cofire", ascending=False).to_csv(out_csv, index=False)

    # ---- report ----
    print("==== P0 CO-FIRE FEASIBILITY (strict-AND, same-direction) ====")
    print(f"pairs={len(pairs)}  evaluators={len(EVALUATORS)}  n_floor={N_FLOOR}")
    print(f"evaluator-pair x direction combos: {len(df)}")
    print()
    print("solo fresh-fire counts (summed across all 17 pairs, ~16k bars each):")
    for e in EVALUATORS:
        print(f"  {e:9s} long={solo[e]['long']:6d}  short={solo[e]['short']:6d}")
    print()

    # An (A,B,dir) combo is "testable somewhere" if >=1 forex-pair cell clears n_floor.
    testable = df[df["testable_pair_cells"] > 0]
    print(f"evaluator-pair x direction combos with >=1 testable forex-pair cell "
          f"(>= {N_FLOOR} same-dir co-fires): {len(testable)} / {len(df)}")
    print()
    print("TOP 20 combos by best single forex-pair cell:")
    print(f"  {'A':9s} {'B':9s} {'dir':5s} {'best_cell':>9s} {'total':>7s} {'testable_cells':>14s}")
    for r in df.sort_values("max_pair_cofire", ascending=False).head(20).itertuples(index=False):
        print(f"  {r.a:9s} {r.b:9s} {r.direction:5s} {r.max_pair_cofire:9d} "
              f"{r.total_cofire:7d} {r.testable_pair_cells:14d}")
    print()
    # Distinct evaluator pairs (either direction) that are testable at all
    testable_pairs = {(r.a, r.b) for r in testable.itertuples(index=False)}
    all_pairs = set(combinations(EVALUATORS, 2))
    print(f"distinct evaluator pairs testable in >=1 (forex_pair,direction) cell: "
          f"{len(testable_pairs)} / {len(all_pairs)}")
    dead = sorted(all_pairs - testable_pairs)
    print(f"evaluator pairs with NO testable cell in either direction: {len(dead)}")
    for a, b in dead:
        print(f"  - {a} + {b}")
    print()
    print(f"saved -> {out_csv}")


if __name__ == "__main__":
    main()
