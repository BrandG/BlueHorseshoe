"""Figures for the study. Each saves a PNG under figures/ (gitignored) and prints the path.
Email with:  ./run.sh python src/send_file_email.py <png> --subject "..."
"""
import os
import config as C
import data as D
from strategy import simulate, build_setup

FIG = os.path.join(C.STUDY_DIR, "figures")


def _ax():
    os.makedirs(FIG, exist_ok=True)
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def chart_equity():
    plt = _ax()
    from datetime import datetime
    S = sorted(D.build_setups(C.SYMBOLS_PRIMARY), key=lambda s: (s["_day"], s["entry"]))
    fig, ax = plt.subplots(figsize=(13, 7))
    for name, bb, keep, col in [("Baseline", 0.0, None, "#888888"),
                                ("A: extreme not last 2min", 0.0, lambda s: s["ext_from_end"] >= 2, "#d62728"),
                                ("B: bounce 0.2R first", 0.20, None, "#2ca02c")]:
        xs, ys, cum = [], [], 0.0
        for s in S:
            if keep and not keep(s):
                continue
            out, pnl = simulate(s, bb)
            if out == "NEVER_FILLED":
                continue
            cum += pnl - (C.COST_PER_SHARE / s["U"] if s["U"] else 0)
            xs.append(datetime.strptime(s["_day"], "%Y-%m-%d")); ys.append(cum)
        ax.plot(xs, ys, label=f"{name}  (end {ys[-1]:+.0f}U)", color=col, lw=1.8)
    ax.axvline(datetime.strptime(C.OOS_SPLIT, "%Y-%m-%d"), color="black", ls=":", lw=1.2)
    ax.axhline(0, color="black", lw=0.6, alpha=0.5)
    ax.set_title("Opening-range fade: cumulative net P&L (12 stocks). Left of dotted line = out-of-sample.")
    ax.set_ylabel("Cumulative net U"); ax.legend(loc="upper left"); ax.grid(alpha=0.25)
    fig.autofmt_xdate()
    p = os.path.join(FIG, "equity.png"); fig.savefig(p, dpi=115, bbox_inches="tight")
    print("saved", p)


def chart_scatter():
    plt = _ax(); import statistics
    pts = []
    for t in C.SYMBOLS_INDEX + C.SYMBOLS_HOLDOUT:
        st = D.build_setups([t]); pr = []; pn = []; us = []
        for s in st:
            out, pnl = simulate(s, C.BOUNCE_B)
            if out == "NEVER_FILLED":
                continue
            pr.append(s["entry"]); pn.append(pnl); us.append(s["U"])
        if not pn:
            continue
        net = sum(pn) - C.COST_PER_SHARE * sum(1/u for u in us)
        pts.append((t, statistics.median(pr), net))
    fig, ax = plt.subplots(figsize=(12, 7))
    for t, price, net in pts:
        ax.scatter(price, net, s=70, color="#2ca02c" if net > 0 else "#d62728", edgecolor="black", lw=0.6)
        ax.annotate(t, (price, net), xytext=(4, 4), textcoords="offset points", fontsize=9)
    ax.axhline(0, color="black", lw=1); ax.set_xscale("log")
    ax.set_xlabel("Share price ($, log)"); ax.set_ylabel("Net result @2c/share (U)")
    ax.set_title("ETF net P&L vs price: costs kill cheap penny-quoted names"); ax.grid(alpha=0.3, which="both")
    p = os.path.join(FIG, "price_vs_net.png"); fig.savefig(p, dpi=115, bbox_inches="tight")
    print("saved", p)


def chart_failures(n=4):
    plt = _ax()
    import pandas as pd
    losses = []
    for sym in C.SYMBOLS_PRIMARY:
        days = D.load_intraday(sym)
        for day, bars in days.items():
            s = build_setup(bars)
            if not s:
                continue
            out, _ = simulate(s, 0.0)
            if out == "LOSS":
                losses.append((sym, day, s, bars))
            if len(losses) >= n:
                break
        if len(losses) >= n:
            break
    for i, (sym, day, s, bars) in enumerate(losses[:n], 1):
        import mplfinance as mpf
        rows = [(f"{day} {hm}", o, h, l, c) for hm, o, h, l, c in bars if hm <= C.SIM_END]
        df = pd.DataFrame(rows, columns=["dt", "Open", "High", "Low", "Close"])
        df["dt"] = pd.to_datetime(df["dt"]); df.set_index("dt", inplace=True)
        sl = s["entry"] - s["U"] if s["side"] == "LONG" else s["entry"] + s["U"]
        fig, axes = mpf.plot(df, type="candle", style="yahoo", returnfig=True, figsize=(12, 6),
                             title=f"\n{sym} {day} {s['side']} fade -> LOSS")
        ax = axes[0]
        ax.axhline(s["entry"], color="#1f77b4", lw=1.5, label=f"entry {s['entry']:.2f}")
        ax.axhline(s["tp"], color="#2ca02c", lw=1.5, ls="--", label=f"target {s['tp']:.2f}")
        ax.axhline(sl, color="#d62728", lw=1.5, ls="--", label=f"stop {sl:.2f}")
        ax.legend(loc="upper left", fontsize=9)
        p = os.path.join(FIG, f"failure_{i}_{sym}_{day}.png"); fig.savefig(p, dpi=110, bbox_inches="tight")
        print("saved", p)
