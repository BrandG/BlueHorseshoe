"""Draw the price chart with v3 S/R levels overlaid + touches marked, so levels can
be eyeballed visually instead of reconstructed from a table.

Usage:
    python chart_levels.py SYMBOL [TOP_N] [AS_OF_DATE] [START]
Defaults: SYMBOL=AAPL, TOP_N=8 strongest active levels, AS_OF=last bar.

Writes <SYMBOL>_chart.png next to this script. Support levels (below price) are
green, resistance (above) red; line weight ~ strength; dots mark each touch date.
"""
import sys, os
import numpy as np, pandas as pd, duckdb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(__file__))
from detector_v3 import detect, active_levels, dedupe_levels, range_score, SRParamsV3  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(os.path.abspath(os.path.join(HERE, "..", "..")), "data", "ohlcv.duckdb")


def main():
    symbol = sys.argv[1].upper() if len(sys.argv) > 1 else "AAPL"
    top_n = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    as_of_date = sys.argv[3] if len(sys.argv) > 3 else None
    start = sys.argv[4] if len(sys.argv) > 4 else "2015-01-01"
    params = SRParamsV3()

    con = duckdb.connect(DB, read_only=True)
    d = con.execute("SELECT date,high,low,close FROM ohlcv WHERE symbol=? AND date>=? "
                    "ORDER BY date", [symbol, start]).df()
    con.close()
    if d.empty:
        print(f"No rows for {symbol}"); return

    dt = pd.to_datetime(d.date)
    h, l, c = (d[x].to_numpy(float) for x in ("high", "low", "close"))
    n = len(c)
    as_of = n - 1
    if as_of_date:
        le = np.where(dt.dt.strftime("%Y-%m-%d").to_numpy() <= as_of_date)[0]
        if len(le):
            as_of = int(le[-1])

    clusters, atr = detect(h, l, c, params)
    live = active_levels(clusters, as_of, params, atr)
    live = dedupe_levels(live, atr[as_of], min_sep_atr=1.0)   # one line per zone
    live = sorted(live, key=lambda z: -z.strength)[:top_n]
    if not live:
        print(f"{symbol}: no active levels to chart"); return
    close_at = c[as_of]

    # display window: from a bit before the earliest shown touch, to as_of
    first = min(min(v.touch_bars) for v in live)
    x0 = max(0, first - 20)
    sl = slice(x0, as_of + 1)
    xd = dt.iloc[sl]

    smax = max(v.strength for v in live) or 1.0
    fig, ax = plt.subplots(figsize=(15, 8))
    ax.plot(xd, c[sl], color="#222", lw=1.0, zorder=3, label="close")

    for v in live:
        role = "support" if v.center < close_at else "resistance"
        col = "#1a8a3a" if role == "support" else "#c01616"
        lw = 1.0 + 3.0 * (v.strength / smax)
        x_start = dt.iloc[min(v.touch_bars)]
        ax.hlines(v.center, x_start, xd.iloc[-1], color=col, lw=lw, alpha=0.55, zorder=2)
        # touch dots at the ACTUAL consolidation price (not the line) so over-merges show
        pts = [(b, p) for b, p in zip(v.touch_bars, v.touch_prices) if b >= x0]
        if pts:
            ax.scatter([dt.iloc[b] for b, _ in pts], [p for _, p in pts], color=col,
                       s=28, zorder=4, edgecolor="white", linewidth=0.5)
        ax.annotate(f"{v.center:.2f}  ({v.touches}: S{v.up_touches}/R{v.down_touches})",
                    xy=(xd.iloc[-1], v.center), xytext=(6, 0),
                    textcoords="offset points", va="center", fontsize=8, color=col)

    ax.axhline(close_at, color="#888", ls="--", lw=0.8, zorder=1)
    rs = range_score(c)
    ax.set_title(f"{symbol} — v3 S/R (top {len(live)} by strength) as of "
                 f"{dt.iloc[as_of]:%Y-%m-%d}   close={close_at:.2f}  ER={rs:.3f}")
    ax.set_ylabel("price"); ax.margins(x=0.02)
    ax.grid(True, alpha=0.2)
    fig.autofmt_xdate()
    fig.tight_layout()
    out = os.path.join(HERE, f"{symbol}_chart.png")
    fig.savefig(out, dpi=130)
    print(f"wrote {out}  ({len(live)} levels, window {xd.iloc[0]:%Y-%m-%d}..{xd.iloc[-1]:%Y-%m-%d})")


if __name__ == "__main__":
    main()
