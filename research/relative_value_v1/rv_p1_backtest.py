"""Relative-Value Phase 1 — carry-aware z-score backtest on the Phase-0 survivors.

For each surviving cointegrated pair (a, b, beta), trade the spread
S = log(A) - beta*log(B) on a causal rolling z-score: enter |z|>2 (bet on
reversion), exit z->0, stop |z|>3.5, time-cap 3x half-life. Net per-trade money
includes BOTH legs' bid/ask AND carry/swap over the hold (OANDA snapshot rates,
annualized, applied uniformly — same approximation as the FTMO backtester). The
question P0 could not answer: does slow reversion survive carry, in per-trade
total money, in BOTH validation halves? Holdout stays reserved for P2.

R is defined risk-normalized like the rest of BUD: risk = stop distance =
(z_stop - z_in)*sigma = 1.5*sigma, so a stop-out ~= -1R and a full reversion
from 2sigma->0 ~= +1.33R before costs. Score = sum of R (total money).
"""
from __future__ import annotations

import glob
import json

import numpy as np
import pandas as pd

from bh_ftmo.data.fx_store import FxStore
from bh_ftmo.indicators._common import ohlc_mid

HOLDOUT_MONTHS = 24
LOOKBACK = 500          # rolling z window (~2x median half-life)
Z_IN, Z_OUT, Z_STOP = 2.0, 0.0, 3.5
TIMECAP_MULT = 3        # close after 3x half-life bars
SURV = "research/relative_value_v1/rv_p0_survivors.csv"

rates = json.load(open(sorted(glob.glob("data/swap_rates_*.json"))[-1]))


def carry_daily(sym, long):
    """Signed annual financing rate for holding `sym` long/short (0 if unknown)."""
    r = rates.get(sym)
    if not r:
        return 0.0
    return r["long_rate"] if long else r["short_rate"]


def load(sym, store):
    df = store.load(sym, granularity="H4", include_incomplete=False)
    df = df.set_index("timestamp")
    mid = ohlc_mid(df)["close"]
    relspread = float(((df["close_ask"] - df["close_bid"]) / mid).median())
    return np.log(mid), relspread


def simulate(a, b, beta, hl, store):
    la, rs_a = load(a, store)
    lb, rs_b = load(b, store)
    df = pd.concat({"la": la, "lb": lb}, axis=1, sort=False).dropna()
    cutoff = df.index.max() - pd.DateOffset(months=HOLDOUT_MONTHS)
    df = df[df.index < cutoff]                                   # pre-holdout only
    S = df["la"] - beta * df["lb"]
    mu = S.rolling(LOOKBACK).mean()
    sd = S.rolling(LOOKBACK).std()
    z = (S - mu) / sd
    bidask = rs_a + abs(beta) * rs_b                            # round-trip, both legs
    timecap = int(TIMECAP_MULT * hl)

    ts = df.index.to_numpy()
    Sv, zv, sdv = S.to_numpy(), z.to_numpy(), sd.to_numpy()
    trades, pos = [], None
    for i in range(LOOKBACK, len(df)):
        if not np.isfinite(zv[i]):
            continue
        if pos is None:
            if abs(zv[i]) > Z_IN:
                side = -1 if zv[i] > 0 else 1                   # short spread if rich
                pos = dict(i0=i, side=side, S0=Sv[i], sd0=sdv[i])
        else:
            zi, held = zv[i], i - pos["i0"]
            hit_mean = (pos["side"] == -1 and zi <= Z_OUT) or (pos["side"] == 1 and zi >= Z_OUT)
            hit_stop = abs(zi) > Z_STOP
            if hit_mean or hit_stop or held >= timecap:
                days = (ts[i] - ts[pos["i0"]]) / np.timedelta64(1, "D")
                gross = pos["side"] * (Sv[i] - pos["S0"])      # spread return captured
                # carry: position holds +side of A and -side*beta of B
                wA, wB = pos["side"], -pos["side"] * beta
                cA = abs(wA) * carry_daily(a, wA > 0)
                cB = abs(wB) * carry_daily(b, wB > 0)
                carry = (cA + cB) * days / 365.0               # signed (credit +/charge -)
                net = gross + carry - bidask
                R = net / (1.5 * pos["sd0"]) if pos["sd0"] > 0 else 0.0
                trades.append(dict(entry=ts[pos["i0"]], R=R, win=net > 0,
                                   days=days, carry=carry, gross=gross,
                                   stop=hit_stop and not hit_mean))
                pos = None
    return pd.DataFrame(trades)


def block(ts):
    t = pd.Timestamp(ts)
    return "A" if (t.year * 4 + t.quarter - 1) % 2 == 0 else "B"


def main():
    surv = pd.read_csv(SURV)
    surv = surv[surv["passes"]].copy()
    print(f"backtesting {len(surv)} Phase-0 survivors (pre-holdout, both halves)\n")
    store = FxStore(read_only=True)
    rows, all_tr = [], []
    try:
        for _, r in surv.iterrows():
            tr = simulate(r["a"], r["b"], r["beta"], r["half_life_bars"], store)
            if tr.empty:
                continue
            tr["pair"] = f"{r['a']}/{r['b']}"
            tr["blk"] = tr["entry"].map(block)
            all_tr.append(tr)
            gA, gB = tr[tr.blk == "A"], tr[tr.blk == "B"]
            rows.append(dict(pair=f"{r['a']}/{r['b']}", n=len(tr),
                             wr=tr.win.mean(), totR=tr.R.sum(), avgR=tr.R.mean(),
                             RA=gA.R.sum(), RB=gB.R.sum(),
                             both=gA.R.sum() > 0 and gB.R.sum() > 0,
                             med_days=tr.days.median()))
    finally:
        store.close()
    T = pd.DataFrame(rows).sort_values("totR", ascending=False)
    pd.set_option("display.width", 200, "display.max_columns", 30)
    show = T.copy()
    for c in ["wr", "totR", "avgR", "RA", "RB", "med_days"]:
        show[c] = show[c].map(lambda x: f"{x:.2f}")
    print(show.to_string(index=False))

    A = pd.concat(all_tr, ignore_index=True)
    print(f"\n=== POOLED (all {len(surv)} pairs) ===")
    for blk in ["A", "B"]:
        g = A[A.blk == blk]
        se = g.R.std() / np.sqrt(len(g)) if len(g) > 1 else float("nan")
        print(f"  block {blk}: {len(g):5d} trades | win {g.win.mean()*100:4.1f}% | "
              f"avg R {g.R.mean():+.3f} | total R {g.R.sum():+7.1f} | "
              f"z {g.R.mean()/se:+.2f}")
    print(f"  carry: median {A.carry.median():+.4f} / trade | "
          f"stop-outs {A.stop.mean()*100:.0f}% | median hold {A.days.median():.0f}d")
    n_both = int(T["both"].sum())
    bookpos = A[A.blk == "A"].R.sum() > 0 and A[A.blk == "B"].R.sum() > 0
    print(f"\n  pairs profitable in BOTH halves: {n_both}/{len(T)} "
          f"(per-cell is noisy — judge at the book level)")
    # Book-level read (the campaign law: the book survives even when per-cell collapses).
    # NOT a significance claim: these z are naive-SE; trades overlap AND the pairs share
    # legs (cross-correlated), so Newey-West + clustering will shrink the SE — block B is
    # already marginal. And selection is in-sample (pairs chosen on this same pre-holdout).
    print("  BOOK-LEVEL: " + (
        "positive in BOTH halves net of carry — PROMISING, but naive-SE; carry is a non-issue. "
        "Decider = P2 (2024-26 holdout + Newey-West/cluster SE + rolling beta)."
        if bookpos else
        "not positive in both halves — book does not survive."))
    A.to_csv("research/relative_value_v1/rv_p1_trades.csv", index=False)


if __name__ == "__main__":
    main()
