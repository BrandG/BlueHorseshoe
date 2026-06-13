"""Newey-West re-gate of the v2 production cells on the archived spread ledgers.

Replicates the original expectancy gate (iid SE, 70/30 chronological split,
CI_low > 0 on both halves) per deployed cell, then recomputes the same CI with
Bartlett-kernel Newey-West SE. Lag per half is derived from the actual overlap
structure of the trades: L_i = #{j > i : entry_ts[j] < exit_ts[i]} (trades open
concurrently with trade i). Primary lag = p95 of L_i (rounded up); sensitivity
column at L_max.

Ledgers: /tmp/nw_regate/ledgers/<strategy>_<entrymode>.csv (pair,entry_ts,exit_ts,r)
Cell directions come from the live deployment list (bud.briefing.CELLS).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "/root/BlueHorseshoe/src")
from bud.briefing import CELLS  # noqa: E402

LEDGER_DIR = Path("/tmp/nw_regate/ledgers")
TRAIN_FRAC = 0.7

# strategy name in CELLS -> ledger file stem
LEDGER_FILE = {
    "stoch": "stoch_mid", "bb": "bb_mid", "cci": "cci_mid", "ema": "ema_mid",
    "sma": "sma_mid", "rsi": "rsi_mid", "candle": "candlestick_mid",
    "macd": "macd_limit", "atr": "atr_limit", "ichimoku": "ichimoku_limit",
}


def nw_se(rs: np.ndarray, lag: int) -> float:
    """Newey-West (Bartlett) standard error of the mean."""
    n = len(rs)
    if n < 2:
        return float("nan")
    d = rs - rs.mean()
    gamma0 = float(d @ d) / n
    var = gamma0
    lag = min(lag, n - 1)
    for l in range(1, lag + 1):
        w = 1.0 - l / (lag + 1.0)
        gamma_l = float(d[l:] @ d[:-l]) / n
        var += 2.0 * w * gamma_l
    var = max(var, 0.0)  # kernel can go slightly negative on tiny n
    return float(np.sqrt(var / n))


def overlap_lags(entry: np.ndarray, exit_: np.ndarray) -> tuple[int, int]:
    """(p95, max) of per-trade forward overlap counts, on entry_ts-sorted trades."""
    n = len(entry)
    if n < 2:
        return 0, 0
    counts = np.empty(n, dtype=int)
    for i in range(n):
        # trades are sorted by entry; count subsequent entries before exit_[i]
        counts[i] = int(np.searchsorted(entry[i + 1:], exit_[i], side="left"))
    p95 = int(np.ceil(np.percentile(counts, 95)))
    return p95, int(counts.max())


def half_stats(df: pd.DataFrame) -> dict:
    rs = df["r"].to_numpy(dtype=float)
    n = len(rs)
    out = {"n": n, "mean": np.nan, "iid_se": np.nan, "iid_lo": np.nan,
           "lag95": 0, "lagmax": 0, "nw_se": np.nan, "nw_lo": np.nan,
           "nwmax_lo": np.nan}
    if n == 0:
        return out
    out["mean"] = float(rs.mean())
    if n < 2:
        return out
    iid = float(rs.std(ddof=1) / np.sqrt(n))
    out["iid_se"] = iid
    out["iid_lo"] = out["mean"] - 1.96 * iid
    entry = df["entry_ts"].to_numpy(dtype="datetime64[ns]")
    exit_ = df["exit_ts"].to_numpy(dtype="datetime64[ns]")
    lag95, lagmax = overlap_lags(entry, exit_)
    out["lag95"], out["lagmax"] = lag95, lagmax
    se95 = nw_se(rs, lag95)
    semax = nw_se(rs, lagmax)
    out["nw_se"] = se95
    out["nw_lo"] = out["mean"] - 1.96 * se95
    out["nwmax_lo"] = out["mean"] - 1.96 * semax
    return out


def main() -> None:
    ledgers: dict[str, pd.DataFrame] = {}
    for strat, stem in LEDGER_FILE.items():
        df = pd.read_csv(LEDGER_DIR / f"{stem}.csv",
                         parse_dates=["entry_ts", "exit_ts"])
        ledgers[strat] = df

    rows = []
    for cell in CELLS:
        led = ledgers[cell.strategy]
        sub = (led[led["pair"] == cell.pair]
               .sort_values("entry_ts").reset_index(drop=True))
        if sub.empty:
            rows.append({"strategy": cell.strategy, "pair": cell.pair,
                         "direction": cell.direction, "note": "NO LEDGER TRADES"})
            continue
        cut = int(len(sub) * TRAIN_FRAC)
        tr, te = half_stats(sub.iloc[:cut]), half_stats(sub.iloc[cut:])
        orig_pass = (tr["iid_lo"] > 0 and te["iid_lo"] > 0
                     and tr["n"] >= 50 and te["n"] >= 30)
        nw_pass = (tr["nw_lo"] > 0 and te["nw_lo"] > 0
                   and tr["n"] >= 50 and te["n"] >= 30)
        nwmax_pass = (tr["nwmax_lo"] > 0 and te["nwmax_lo"] > 0
                      and tr["n"] >= 50 and te["n"] >= 30)
        rows.append({
            "strategy": cell.strategy, "pair": cell.pair,
            "direction": cell.direction, "entry_mode": cell.entry_mode,
            "tr_n": tr["n"], "te_n": te["n"],
            "tr_mean": tr["mean"], "te_mean": te["mean"],
            "tr_iid_lo": tr["iid_lo"], "te_iid_lo": te["iid_lo"],
            "tr_lag95": tr["lag95"], "te_lag95": te["lag95"],
            "tr_lagmax": tr["lagmax"], "te_lagmax": te["lagmax"],
            "se_infl_te": (te["nw_se"] / te["iid_se"]
                           if te["iid_se"] and not np.isnan(te["iid_se"]) else np.nan),
            "tr_nw_lo": tr["nw_lo"], "te_nw_lo": te["nw_lo"],
            "tr_nwmax_lo": tr["nwmax_lo"], "te_nwmax_lo": te["nwmax_lo"],
            "orig_pass": orig_pass, "nw_pass": nw_pass, "nwmax_pass": nwmax_pass,
            "note": "",
        })

    res = pd.DataFrame(rows)
    res.to_csv("/tmp/nw_regate/nw_regate_results.csv", index=False)

    pd.set_option("display.width", 200)
    cols = ["strategy", "pair", "direction", "tr_n", "te_n",
            "tr_mean", "te_mean", "tr_iid_lo", "te_iid_lo",
            "tr_nw_lo", "te_nw_lo", "te_lag95", "se_infl_te",
            "orig_pass", "nw_pass", "nwmax_pass"]
    with pd.option_context("display.float_format", "{:+.3f}".format):
        print(res[cols].to_string(index=False))

    ok = res[res["orig_pass"] == True]  # noqa: E712
    flips = ok[ok["nw_pass"] == False]  # noqa: E712
    print(f"\nDeployed cells with ledger trades: {len(res[res['note'] == ''])}")
    print(f"Original iid gate passes (replicated): {int(res['orig_pass'].sum())}")
    print(f"Survive NW(p95-lag) gate:             {int(res['nw_pass'].sum())}")
    print(f"Survive NW(max-lag) gate:             {int(res['nwmax_pass'].sum())}")
    if not flips.empty:
        print("\nFLIPPED by NW (passed iid, fail NW p95):")
        for _, r in flips.iterrows():
            print(f"  {r['strategy']:<9} {r['pair']:<8} {r['direction']:<5} "
                  f"te_mean={r['te_mean']:+.3f} iid_lo={r['te_iid_lo']:+.3f} "
                  f"nw_lo={r['te_nw_lo']:+.3f} (tr_nw_lo={r['tr_nw_lo']:+.3f})")


if __name__ == "__main__":
    main()
