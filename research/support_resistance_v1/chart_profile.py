"""Volume-Profile-style chart: price on the left, the recency+volume price
histogram sideways on the right, peaks drawn as S/R lines across the chart.

Usage: python chart_profile.py SYMBOL [START]
Writes <SYMBOL>_profile.png next to this script.
"""
import sys, os
import numpy as np, pandas as pd, duckdb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

sys.path.insert(0, os.path.dirname(__file__))
from profile import compute_profile, ProfileParams  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(os.path.abspath(os.path.join(HERE, "..", "..")), "data", "ohlcv.duckdb")


def main():
    symbol = sys.argv[1].upper() if len(sys.argv) > 1 else "AAPL"
    start = sys.argv[2] if len(sys.argv) > 2 else "2015-01-01"
    params = ProfileParams()

    con = duckdb.connect(DB, read_only=True)
    d = con.execute("SELECT date,high,low,close,volume FROM ohlcv WHERE symbol=? AND date>=? "
                    "ORDER BY date", [symbol, start]).df()
    con.close()
    if d.empty:
        print(f"No rows for {symbol}"); return

    dt = pd.to_datetime(d.date)
    h, l, c, v = (d[x].to_numpy(float) for x in ("high", "low", "close", "volume"))
    as_of = len(c) - 1
    centers, prof, peaks, atr_at, lo_bar = compute_profile(h, l, c, v, params, as_of)
    close_at = c[as_of]
    sl = slice(lo_bar, as_of + 1)

    fig = plt.figure(figsize=(15, 8))
    gs = GridSpec(1, 5, figure=fig, wspace=0.02)
    axp = fig.add_subplot(gs[0, :4])
    axh = fig.add_subplot(gs[0, 4], sharey=axp)

    axp.plot(dt.iloc[sl], c[sl], color="#222", lw=1.0, zorder=3)
    axp.axhline(close_at, color="#888", ls="--", lw=0.8, zorder=1)
    wmax = max(p["weight"] for p in peaks) if peaks else 1.0
    for pk in peaks:
        role = "support" if pk["price"] < close_at else "resistance"
        col = "#1a8a3a" if role == "support" else "#c01616"
        lw = 1.0 + 3.0 * (pk["weight"] / wmax)
        axp.axhline(pk["price"], color=col, lw=lw, alpha=0.5, zorder=2)
        axp.annotate(f"{pk['price']:.2f}", xy=(dt.iloc[as_of], pk["price"]),
                     xytext=(4, 0), textcoords="offset points", va="center",
                     fontsize=8, color=col)

    # right: the histogram itself (sideways)
    axh.fill_betweenx(centers, 0, prof, color="#4477aa", alpha=0.5, step="mid")
    axh.plot(prof, centers, color="#225588", lw=0.8)
    for pk in peaks:
        col = "#1a8a3a" if pk["price"] < close_at else "#c01616"
        axh.axhline(pk["price"], color=col, lw=1.0, alpha=0.5)
    axh.set_xticks([]); axh.tick_params(labelleft=False)
    axh.set_xlabel("vol×recency", fontsize=8)

    axp.set_title(f"{symbol} — Volume-Profile S/R (recency+volume histogram peaks) "
                  f"as of {dt.iloc[as_of]:%Y-%m-%d}  close={close_at:.2f}")
    axp.set_ylabel("price"); axp.grid(True, alpha=0.2); axp.margins(x=0.02)
    fig.autofmt_xdate()
    out = os.path.join(HERE, f"{symbol}_profile.png")
    fig.savefig(out, dpi=130, bbox_inches="tight")
    print(f"wrote {out}  ({len(peaks)} peak levels)")


if __name__ == "__main__":
    main()
