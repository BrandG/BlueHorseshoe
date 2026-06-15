"""Relative-Value Phase 2 — the decider: out-of-sample holdout + Newey-West.

P1 showed the book positive in both pre-holdout halves, but (a) the pairs were
selected in-sample on that same period and (b) the betas were fit in-sample.
P2 removes both: trade the SAME 15 in-sample-selected pairs FORWARD on the
reserved 2024-2026 holdout, using the pre-holdout beta (estimated entirely
before the holdout => genuinely out-of-sample, no lookahead). Significance is
Newey-West on the pooled per-trade R series ordered by entry (concurrent cross-
pair trades become adjacent, so the NW lag absorbs their correlation).

If the holdout book stays positive and NW-significant => the edge survives
out-of-sample (deploy candidate). If it goes flat/negative => P1 was in-sample
selection, and door #2 closes honestly.
"""
from __future__ import annotations

import glob
import json

import numpy as np
import pandas as pd

from bh_ftmo.data.fx_store import FxStore
from bh_ftmo.indicators._common import ohlc_mid

HOLDOUT_MONTHS = 24
LOOKBACK = 500
Z_IN, Z_OUT, Z_STOP = 2.0, 0.0, 3.5
TIMECAP_MULT = 3
NW_LAG = 15                      # ~ one wave of concurrent cross-pair entries
SURV = "research/relative_value_v1/rv_p0_survivors.csv"

rates = json.load(open(sorted(glob.glob("data/swap_rates_*.json"))[-1]))


def carry_rate(sym, long):
    r = rates.get(sym)
    return (r["long_rate"] if long else r["short_rate"]) if r else 0.0


def load(sym, store):
    df = store.load(sym, granularity="H4", include_incomplete=False).set_index("timestamp")
    mid = ohlc_mid(df)["close"]
    return np.log(mid), float(((df["close_ask"] - df["close_bid"]) / mid).median())


def nw_se(x, L):
    x = np.asarray(x, float); n = len(x)
    if n < 3:
        return float("nan")
    e = x - x.mean()
    g0 = (e @ e) / n
    s = g0
    for k in range(1, min(L, n - 1) + 1):
        gk = (e[k:] @ e[:-k]) / n
        s += 2 * (1 - k / (L + 1)) * gk
    return np.sqrt(max(s, 1e-12) / n)


def simulate(a, b, beta, hl, store, win_start):
    """Trade the spread; emit only trades whose ENTRY is on/after win_start.
    Spread/z are built over the FULL series so z is warmed up from history
    (causal) at the holdout boundary."""
    la, rs_a = load(a, store)
    lb, rs_b = load(b, store)
    df = pd.concat({"la": la, "lb": lb}, axis=1, sort=False).dropna()
    S = df["la"] - beta * df["lb"]
    z = (S - S.rolling(LOOKBACK).mean()) / S.rolling(LOOKBACK).std()
    bidask = rs_a + abs(beta) * rs_b
    timecap = int(TIMECAP_MULT * hl)
    ts = df.index.to_numpy()
    Sv, zv, sd = S.to_numpy(), z.to_numpy(), S.rolling(LOOKBACK).std().to_numpy()
    w0 = np.datetime64(pd.Timestamp(win_start))
    trades, pos = [], None
    for i in range(LOOKBACK, len(df)):
        if not np.isfinite(zv[i]):
            continue
        if pos is None:
            if ts[i] >= w0 and abs(zv[i]) > Z_IN:            # only open inside window
                pos = dict(i0=i, side=-1 if zv[i] > 0 else 1, S0=Sv[i], sd0=sd[i])
        else:
            zi, held = zv[i], i - pos["i0"]
            done = ((pos["side"] == -1 and zi <= Z_OUT) or (pos["side"] == 1 and zi >= Z_OUT)
                    or abs(zi) > Z_STOP or held >= timecap)
            if done:
                days = (ts[i] - ts[pos["i0"]]) / np.timedelta64(1, "D")
                gross = pos["side"] * (Sv[i] - pos["S0"])
                wA, wB = pos["side"], -pos["side"] * beta
                carry = (abs(wA) * carry_rate(a, wA > 0)
                         + abs(wB) * carry_rate(b, wB > 0)) * days / 365.0
                net = gross + carry - bidask
                trades.append(dict(entry=ts[pos["i0"]], R=net / (1.5 * pos["sd0"]) if pos["sd0"] > 0 else 0.0,
                                   win=net > 0))
                pos = None
    return pd.DataFrame(trades)


def book(trades_list, label):
    A = pd.concat(trades_list, ignore_index=True).sort_values("entry")
    se = nw_se(A.R.to_numpy(), NW_LAG)
    naive = A.R.std() / np.sqrt(len(A))
    print(f"  {label:22s}: {len(A):5d} trades | win {A.win.mean()*100:4.1f}% | "
          f"avg R {A.R.mean():+.3f} | total R {A.R.sum():+7.1f} | "
          f"naive z {A.R.mean()/naive:+.2f} | NW z {A.R.mean()/se:+.2f}")
    return A


def main():
    surv = pd.read_csv(SURV)
    surv = surv[surv["passes"]].copy()
    store = FxStore(read_only=True)
    sample = load(surv.iloc[0]["a"], store)[0]
    cutoff = sample.index.max() - pd.DateOffset(months=HOLDOUT_MONTHS)
    pre_start = sample.index.min()
    print(f"holdout = {cutoff.date()} .. {sample.index.max().date()}  "
          f"({len(surv)} in-sample-selected pairs, pre-holdout beta)\n")
    pre, hold, per = [], [], []
    try:
        for _, r in surv.iterrows():
            args = (r["a"], r["b"], r["beta"], r["half_life_bars"], store)
            tp = simulate(*args, pre_start)
            tp = tp[pd.to_datetime(tp.entry) < cutoff] if len(tp) else tp
            th = simulate(*args, cutoff)
            if len(tp):
                pre.append(tp)
            if len(th):
                hold.append(th)
                per.append(dict(pair=f"{r['a']}/{r['b']}", n=len(th),
                                totR=th.R.sum(), avgR=th.R.mean()))
    finally:
        store.close()
    print("=== BOOK-LEVEL ===")
    book(pre, "pre-holdout (in-sample)")
    H = book(hold, "HOLDOUT (out-of-sample)")
    P = pd.DataFrame(per).sort_values("totR", ascending=False)
    print(f"\n  holdout pairs positive: {int((P.totR>0).sum())}/{len(P)}")
    print(f"  best:  " + ", ".join(f"{x.pair} {x.totR:+.1f}R" for x in P.head(3).itertuples()))
    print(f"  worst: " + ", ".join(f"{x.pair} {x.totR:+.1f}R" for x in P.tail(3).itertuples()))
    se = nw_se(pd.concat(hold).sort_values("entry").R.to_numpy(), NW_LAG)
    m = pd.concat(hold).R.mean()
    print("\n  VERDICT: " + (
        "SURVIVES out-of-sample — holdout book positive & NW-significant. Door #2 is real → P3 (deploy design)."
        if m > 0 and m / se > 1.64 else
        "holdout positive but NW-marginal — suggestive, not conclusive." if m > 0 else
        "FAILS out-of-sample — holdout book not positive. P1 was in-sample selection; door #2 closes."))
    pd.concat(hold).to_csv("research/relative_value_v1/rv_p2_holdout_trades.csv", index=False)


if __name__ == "__main__":
    main()
