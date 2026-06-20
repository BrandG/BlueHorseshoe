"""Overlay detected wedges (sloped S/R trendlines) on the candle chart for eyeballing.
Solid segment = between first & last touch; dashed = extrapolation to today; dots = the
inlier touches. Grey dots = all swing pivots (so over/under-detection is visible).

Usage: python chart_wedges.py [SYMBOL] [N_DAYS] [--email]
"""
import sys, os
import numpy as np, pandas as pd, duckdb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(__file__))
from wedges import find_wedges   # noqa: E402

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
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    do_email = "--email" in sys.argv
    symbol = (args[0].upper() if args else "VZ")
    ndays = int(args[1]) if len(args) > 1 else 252

    con = duckdb.connect(DB, read_only=True)
    d = con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? "
                    "ORDER BY date DESC LIMIT ?", [symbol, ndays]).df()
    con.close()
    d = d.iloc[::-1].reset_index(drop=True)
    dt = pd.to_datetime(d.date)
    o, h, l, c = (d[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    x = np.arange(len(c)); up = c >= o; n = len(c)

    res, sup, atr_arr, (highs, lows) = find_wedges(h, l, c)

    fig, ax = plt.subplots(figsize=(16, 9))
    for col, mask in (("#1a8a3a", up), ("#c01616", ~up)):
        idx = np.where(mask)[0]
        ax.vlines(x[idx], l[idx], h[idx], color=col, lw=0.8, zorder=2)
        ax.bar(x[idx], np.abs(c[idx] - o[idx]), bottom=np.minimum(o[idx], c[idx]),
               width=0.6, color=col, zorder=3)
    # all swing pivots in grey so detection coverage is visible
    for b, p in highs:
        ax.scatter(b, p, s=14, color="#999", zorder=4)
    for b, p in lows:
        ax.scatter(b, p, s=14, color="#999", zorder=4)

    def draw(lines, color):
        for L in lines:
            sl, t1, p1, f, la = L["slope"], L["t1"], L["p1"], L["first"], L["last"]
            yf = p1 + sl * (f - t1); yl = p1 + sl * (la - t1); yn = p1 + sl * (n - 1 - t1)
            ax.plot([f, la], [yf, yl], color=color, lw=2.0, alpha=0.9, zorder=5)      # touch span
            ax.plot([la, n - 1], [yl, yn], color=color, lw=1.2, ls="--", alpha=0.6, zorder=5)
            for (tb, tp) in L["inliers"]:
                ax.scatter(tb, tp, s=42, facecolor="none", edgecolor=color, lw=1.6, zorder=6)
            ax.annotate(f"{yn:.2f} ({L['touches']}t)", xy=(n - 1, yn), xytext=(4, 0),
                        textcoords="offset points", va="center", fontsize=8, color=color)

    draw(res, "#c01616")     # resistance
    draw(sup, "#1a8a3a")     # support

    ax.set_title(f"{symbol} — wedges (>=3 touches): {len(res)} resistance, {len(sup)} support  "
                 f"(close={c[-1]:.2f})", fontsize=12)
    ax.set_ylabel("price"); ax.grid(True, alpha=0.2); ax.margins(x=0.01)
    ax.set_ylim(l.min() - atr_arr[-1], h.max() + atr_arr[-1])
    step = max(1, n // 12)
    ax.set_xticks(range(0, n, step))
    ax.set_xticklabels([f"{dt.iloc[i]:%Y-%m-%d}" for i in range(0, n, step)], rotation=45, ha="right")
    fig.tight_layout()
    out = os.path.join(HERE, f"{symbol}_wedges.png")
    fig.savefig(out, dpi=130)
    print(f"wrote {out}")

    if do_email:
        load_env()
        os.environ["EMAIL_RECIPIENT"] = "brandg@gmail.com"
        sys.path.insert(0, os.path.join(REPO, "src"))
        from bluehorseshoe.core.email_service import EmailService
        svc = EmailService()
        if svc.is_configured():
            ok = svc.send(subject=f"{symbol} — sloped S/R wedges (>=3 touches)",
                          text_body=f"{symbol}: {len(res)} resistance, {len(sup)} support wedges. Chart attached.",
                          attachments=[out])
            print("email sent" if ok else "email FAILED")


if __name__ == "__main__":
    main()
