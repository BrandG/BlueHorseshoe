"""Relative-Value P2b — dynamic (rolling) beta last look before closing door #2.

P2 failed out-of-sample with a STATIC pre-holdout beta. Two explanations:
(a) the hedge ratio went stale (a drifting relationship the static beta no longer
fits) — fixable with a rolling beta; or (b) the relationship genuinely broke —
fatal, and rolling beta won't help. This distinguishes them: re-estimate beta on
a trailing window (causal) so it adapts INTO the holdout, lock beta at entry for
each trade's P&L (realistic), and re-run the same OOS book test + Newey-West.

If the holdout book turns positive => it was stale beta, door reopens. If it
still fails => the relationship broke, door #2 closes for good.
"""
from __future__ import annotations

import glob
import json

import numpy as np
import pandas as pd

from bh_ftmo.data.fx_store import FxStore
from bh_ftmo.indicators._common import ohlc_mid

HOLDOUT_MONTHS = 24
BETA_WIN = 750          # trailing window for the rolling hedge ratio (~3x median HL)
LOOKBACK = 500
Z_IN, Z_OUT, Z_STOP = 2.0, 0.0, 3.5
TIMECAP_MULT = 3
NW_LAG = 15
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
    e = x - x.mean(); g0 = (e @ e) / n; s = g0
    for k in range(1, min(L, n - 1) + 1):
        s += 2 * (1 - k / (L + 1)) * ((e[k:] @ e[:-k]) / n)
    return np.sqrt(max(s, 1e-12) / n)


def rolling_beta(la, lb, W):
    mla, mlb = la.rolling(W).mean(), lb.rolling(W).mean()
    cov = (la * lb).rolling(W).mean() - mla * mlb
    var = (lb * lb).rolling(W).mean() - mlb * mlb
    return cov / var


def simulate(a, b, hl, store, win_start):
    la, rs_a = load(a, store)
    lb, rs_b = load(b, store)
    df = pd.concat({"la": la, "lb": lb}, axis=1, sort=False).dropna()
    la, lb = df["la"], df["lb"]
    beta = rolling_beta(la, lb, BETA_WIN)
    Sdyn = la - beta * lb                                   # rolling-beta spread (for the signal)
    z = (Sdyn - Sdyn.rolling(LOOKBACK).mean()) / Sdyn.rolling(LOOKBACK).std()
    sd = Sdyn.rolling(LOOKBACK).std()
    timecap = int(TIMECAP_MULT * hl)
    ts = df.index.to_numpy()
    lav, lbv, bv, zv, sdv = la.to_numpy(), lb.to_numpy(), beta.to_numpy(), z.to_numpy(), sd.to_numpy()
    w0 = np.datetime64(pd.Timestamp(win_start))
    trades, pos = [], None
    for i in range(BETA_WIN + LOOKBACK, len(df)):
        if not np.isfinite(zv[i]) or not np.isfinite(bv[i]):
            continue
        if pos is None:
            if ts[i] >= w0 and abs(zv[i]) > Z_IN:
                pos = dict(i0=i, side=-1 if zv[i] > 0 else 1, be=bv[i], sd0=sdv[i])
        else:
            zi, held = zv[i], i - pos["i0"]
            if ((pos["side"] == -1 and zi <= Z_OUT) or (pos["side"] == 1 and zi >= Z_OUT)
                    or abs(zi) > Z_STOP or held >= timecap):
                be = pos["be"]                              # beta LOCKED at entry
                days = (ts[i] - ts[pos["i0"]]) / np.timedelta64(1, "D")
                gross = pos["side"] * ((lav[i] - be * lbv[i]) - (lav[pos["i0"]] - be * lbv[pos["i0"]]))
                wA, wB = pos["side"], -pos["side"] * be
                carry = (abs(wA) * carry_rate(a, wA > 0)
                         + abs(wB) * carry_rate(b, wB > 0)) * days / 365.0
                net = gross + carry - (rs_a + abs(be) * rs_b)
                trades.append(dict(entry=ts[pos["i0"]], R=net / (1.5 * pos["sd0"]) if pos["sd0"] > 0 else 0.0,
                                   win=net > 0))
                pos = None
    return pd.DataFrame(trades)


def book(tl, label):
    A = pd.concat(tl, ignore_index=True).sort_values("entry")
    se = nw_se(A.R.to_numpy(), NW_LAG); naive = A.R.std() / np.sqrt(len(A))
    print(f"  {label:26s}: {len(A):5d} trades | win {A.win.mean()*100:4.1f}% | "
          f"avg R {A.R.mean():+.3f} | total R {A.R.sum():+7.1f} | "
          f"naive z {A.R.mean()/naive:+.2f} | NW z {A.R.mean()/se:+.2f}")
    return A


def main():
    surv = pd.read_csv(SURV)
    surv = surv[surv["passes"]].copy()
    store = FxStore(read_only=True)
    sample = load(surv.iloc[0]["a"], store)[0]
    cutoff = sample.index.max() - pd.DateOffset(months=HOLDOUT_MONTHS)
    print(f"dynamic-beta (rolling W={BETA_WIN}) | holdout {cutoff.date()}..{sample.index.max().date()}\n")
    pre, hold, per = [], [], []
    try:
        for _, r in surv.iterrows():
            tp = simulate(r["a"], r["b"], r["half_life_bars"], store, sample.index.min())
            if len(tp):
                tp = tp[pd.to_datetime(tp.entry) < cutoff]
            th = simulate(r["a"], r["b"], r["half_life_bars"], store, cutoff)
            if len(tp):
                pre.append(tp)
            if len(th):
                hold.append(th)
                per.append(dict(pair=f"{r['a']}/{r['b']}", totR=th.R.sum()))
    finally:
        store.close()
    print("=== BOOK-LEVEL (dynamic beta) ===")
    book(pre, "pre-holdout (in-sample)")
    book(hold, "HOLDOUT (out-of-sample)")
    P = pd.DataFrame(per)
    H = pd.concat(hold).sort_values("entry")
    se = nw_se(H.R.to_numpy(), NW_LAG); m = H.R.mean()
    print(f"\n  holdout pairs positive: {int((P.totR>0).sum())}/{len(P)}")
    print("  STATIC-beta holdout was: -60.9R, win 38.5%, NW z -1.84 (P2)")
    print("  VERDICT: " + (
        "RESCUED — dynamic beta turns the holdout positive & NW-significant; it was stale beta."
        if m > 0 and m / se > 1.64 else
        "still fails — dynamic beta does NOT rescue the holdout; the relationship broke. Door #2 closed."))


if __name__ == "__main__":
    main()
