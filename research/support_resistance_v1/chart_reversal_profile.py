"""Candle chart + REVERSAL-POINT histogram sidebar (Brand's refinement).

Each swing high (red dot) / swing low (green dot) is a reversal turning point; the
sidebar histograms their prices, recency-weighted. Detected peaks & shoulders (2nd-
derivative method) are drawn as horizontal levels. For comparison, the old time-at-price
profile is overlaid faintly so the difference is visible.

Usage: python chart_reversal_profile.py [SYMBOL] [N_DAYS] [HALFLIFE] [count|magnitude] [--email]
"""
import sys, os
import numpy as np, pandas as pd, duckdb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

sys.path.insert(0, os.path.dirname(__file__))
from reversal_profile import build_reversal_profile     # noqa: E402
from irregularities import find_irregularities           # noqa: E402
from profile import compute_profile, ProfileParams       # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DB = os.path.join(REPO, "data", "ohlcv.duckdb")


def load_env():
    p = os.path.join(REPO, ".env")
    if not os.path.exists(p):
        return
    for line in open(p):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, val = line.partition("=")
            os.environ.setdefault(k.strip(), val.strip().strip('"').strip("'"))


def main():
    pos = [a for a in sys.argv[1:] if not a.startswith("--")]
    do_email = "--email" in sys.argv
    symbol = (pos[0].upper() if pos else "VZ")
    ndays = int(pos[1]) if len(pos) > 1 else 252
    halflife = float(pos[2]) if len(pos) > 2 else 126.0
    wmode = pos[3] if len(pos) > 3 else "count"

    con = duckdb.connect(DB, read_only=True)
    d = con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? "
                    "ORDER BY date DESC LIMIT ?", [symbol, ndays]).df()
    con.close()
    d = d.iloc[::-1].reset_index(drop=True)
    dt = pd.to_datetime(d.date)
    o, h, l, c, v = (d[x].to_numpy(float) for x in ("open", "high", "low", "close", "volume"))
    x = np.arange(len(c)); up = c >= o; n = len(c)

    centers, prof, pivots, atr = build_reversal_profile(h, l, c, v, halflife=halflife, weight_mode=wmode)
    irr = find_irregularities(centers, prof, atr)
    binh = (centers[1] - centers[0]) if len(centers) > 1 else atr * 0.25

    # faint comparison: old time-at-price profile on the same bins/window
    pp = ProfileParams(recency_halflife=halflife, window_bars=n)
    tc, tw, _, _, _ = compute_profile(h, l, c, v, pp, weight_mode="frequency")

    fig = plt.figure(figsize=(16, 9))
    gs = fig.add_gridspec(1, 2, width_ratios=[5, 1], wspace=0.02)
    ax = fig.add_subplot(gs[0, 0]); axp = fig.add_subplot(gs[0, 1], sharey=ax)

    for col, mask in (("#1a8a3a", up), ("#c01616", ~up)):
        idx = np.where(mask)[0]
        ax.vlines(x[idx], l[idx], h[idx], color=col, lw=0.8, zorder=2)
        ax.bar(x[idx], np.abs(c[idx] - o[idx]), bottom=np.minimum(o[idx], c[idx]),
               width=0.6, color=col, zorder=3)
    # reversal turning points
    for b, p, kind in pivots:
        ax.scatter(b, p, s=26, color=("#c01616" if kind == "R" else "#1a8a3a"),
                   edgecolor="white", linewidth=0.5, zorder=5)

    axp.barh(centers, prof, height=binh * 0.9, color="#3a6ea5", alpha=0.85, label="reversal pts")
    if tw.max() > 0:                                       # faint time-at-price comparison
        axp.plot(tw / tw.max() * prof.max(), tc, color="#888", lw=1.0, alpha=0.7,
                 label="time-at-price")
    for f in irr:
        ls = "-" if f["kind"] == "peak" else "--"
        axp.axhline(f["price"], color="#d08400", lw=1.0, ls=ls, alpha=0.8)
        ax.axhline(f["price"], color="#d08400", lw=1.0, ls=ls, alpha=0.5, zorder=1)
        ax.annotate(f"{f['price']:.2f} {f['kind'][:4]}", xy=(n - 1, f["price"]), xytext=(4, 0),
                    textcoords="offset points", va="center", fontsize=8, color="#aa6a00")

    ax.set_title(f"{symbol} — reversal-point S/R ({wmode}, halflife {halflife:.0f})  "
                 f"{len(pivots)} turns -> {len(irr)} levels  close={c[-1]:.2f}", fontsize=12)
    ax.set_ylabel("price"); ax.grid(True, alpha=0.2); ax.margins(x=0.01)
    axp.set_xticks([]); axp.grid(True, axis="y", alpha=0.2); axp.legend(fontsize=7, loc="upper right")
    plt.setp(axp.get_yticklabels(), visible=False)
    step = max(1, n // 12)
    ax.set_xticks(range(0, n, step))
    ax.set_xticklabels([f"{dt.iloc[i]:%Y-%m-%d}" for i in range(0, n, step)], rotation=45, ha="right")

    out = os.path.join(HERE, f"{symbol}_reversal_profile.png")
    fig.savefig(out, dpi=130, bbox_inches="tight")
    print(f"wrote {out}  ({len(pivots)} pivots, {len(irr)} levels: "
          f"{[round(f['price'],2) for f in irr]})")

    if do_email:
        load_env(); os.environ["EMAIL_RECIPIENT"] = "brandg@gmail.com"
        sys.path.insert(0, os.path.join(REPO, "src"))
        from bluehorseshoe.core.email_service import EmailService
        svc = EmailService()
        if svc.is_configured():
            lv = ", ".join(f"{f['price']:.2f}({f['kind'][:4]})" for f in irr)
            ok = svc.send(subject=f"{symbol} — reversal-point S/R histogram",
                          text_body=(f"{symbol}: {len(pivots)} reversal turns -> levels: {lv}. "
                                     f"Sidebar = histogram of reversal prices ({wmode}, recency "
                                     f"halflife {halflife:.0f}); grey line = old time-at-price."),
                          attachments=[out])
            print("email sent" if ok else "email FAILED")


if __name__ == "__main__":
    main()
