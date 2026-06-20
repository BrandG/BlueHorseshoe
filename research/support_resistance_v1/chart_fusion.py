"""Chart the FUSION levels (profile-located + reaction-validated) with touches.
Usage: python chart_fusion.py SYMBOL [TOP_N] [START]
"""
import sys, os
import numpy as np, pandas as pd, duckdb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(__file__))
from fusion import fuse_levels  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(os.path.abspath(os.path.join(HERE, "..", "..")), "data", "ohlcv.duckdb")


def main():
    symbol = sys.argv[1].upper() if len(sys.argv) > 1 else "AAPL"
    top_n = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    start = sys.argv[3] if len(sys.argv) > 3 else "2015-01-01"

    con = duckdb.connect(DB, read_only=True)
    d = con.execute("SELECT date,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? "
                    "ORDER BY date", [symbol, start]).df()
    con.close()
    if d.empty:
        print(f"No rows for {symbol}"); return
    dt = pd.to_datetime(d.date)
    h, l, c, v = (d[x].to_numpy(float) for x in ("high", "low", "close", "volume"))
    levels, atr, atr_at, as_of = fuse_levels(h, l, c, v)
    levels = levels[:top_n]
    if not levels:
        print(f"{symbol}: no fused levels"); return
    close_at = c[as_of]

    first = min(min(e[1] for e in lv["reactions"]) for lv in levels)
    x0 = max(0, first - 20)
    sl = slice(x0, as_of + 1)
    xd = dt.iloc[sl]
    wmax = max(lv["weight"] for lv in levels) or 1.0

    fig, ax = plt.subplots(figsize=(15, 8))
    ax.plot(xd, c[sl], color="#222", lw=1.0, zorder=3)
    ax.axhline(close_at, color="#888", ls="--", lw=0.8, zorder=1)
    for lv in levels:
        role = "support" if lv["price"] < close_at else "resistance"
        col = "#1a8a3a" if role == "support" else "#c01616"
        ax.axhline(lv["price"], color=col, lw=1.0 + 3.0 * (lv["weight"] / wmax), alpha=0.5, zorder=2)
        pts = [(e[1], e[2]) for e in lv["reactions"] if e[1] >= x0]
        if pts:
            ax.scatter([dt.iloc[b] for b, _ in pts], [p for _, p in pts], color=col,
                       s=28, zorder=4, edgecolor="white", linewidth=0.5)
        ax.annotate(f"{lv['price']:.2f} ({lv['touches']}: S{lv['up']}/R{lv['down']})",
                    xy=(xd.iloc[-1], lv["price"]), xytext=(6, 0), textcoords="offset points",
                    va="center", fontsize=8, color=col)
    ax.set_title(f"{symbol} — FUSION S/R (profile peak + reactions) as of {dt.iloc[as_of]:%Y-%m-%d} "
                 f"close={close_at:.2f}")
    ax.set_ylabel("price"); ax.grid(True, alpha=0.2); ax.margins(x=0.02)
    fig.autofmt_xdate(); fig.tight_layout()
    out = os.path.join(HERE, f"{symbol}_fusion.png")
    fig.savefig(out, dpi=130)
    print(f"wrote {out} ({len(levels)} levels)")


if __name__ == "__main__":
    main()
