"""Price + volume chart with a RECENCY-WEIGHTED FREQUENCY profile sidebar.

Same candle/volume picture as chart_price_volume.py, plus a horizontal histogram on
the right that shares the price axis: each price bin's bar = how often price visited
that level (time-at-price), with recent bars weighted more than old ones. The long
bars are the prices the market keeps coming back to = candidate S/R bands.

Usage: python chart_price_profile.py [SYMBOL] [N_DAYS] [HALFLIFE_BARS]
Defaults: SYMBOL=VZ, N_DAYS=252 (~1 yr), HALFLIFE=126 (~6 mo -> clear recency tilt).
"""
import sys, os
import numpy as np, pandas as pd, duckdb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

sys.path.insert(0, os.path.dirname(__file__))
from profile import compute_profile, ProfileParams   # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DB = os.path.join(REPO, "data", "ohlcv.duckdb")


def load_env():
    p = os.path.join(REPO, ".env")
    if not os.path.exists(p):
        return
    for line in open(p):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, val = line.partition("=")
        os.environ.setdefault(k.strip(), val.strip().strip('"').strip("'"))


def main():
    symbol = (sys.argv[1].upper() if len(sys.argv) > 1 else "VZ")
    ndays = int(sys.argv[2]) if len(sys.argv) > 2 else 252
    halflife = float(sys.argv[3]) if len(sys.argv) > 3 else 126.0

    con = duckdb.connect(DB, read_only=True)
    d = con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? "
                    "ORDER BY date DESC LIMIT ?", [symbol, ndays]).df()
    con.close()
    if d.empty:
        print(f"No rows for {symbol}"); return
    d = d.iloc[::-1].reset_index(drop=True)
    dt = pd.to_datetime(d.date)
    o, h, l, c, v = (d[x].to_numpy(float) for x in ("open", "high", "low", "close", "volume"))
    x = np.arange(len(c))
    up = c >= o

    # frequency profile over exactly the charted window, recency-tilted
    pp = ProfileParams(recency_halflife=halflife, window_bars=len(c))
    centers, weights, peaks, atr, _ = compute_profile(h, l, c, v, pp, weight_mode="frequency")
    binh = (centers[1] - centers[0]) if len(centers) > 1 else atr * pp.bin_atr

    fig = plt.figure(figsize=(16, 9))
    gs = fig.add_gridspec(2, 2, width_ratios=[5, 1], height_ratios=[3, 1],
                          wspace=0.02, hspace=0.05)
    ax = fig.add_subplot(gs[0, 0])
    axp = fig.add_subplot(gs[0, 1], sharey=ax)          # profile sidebar shares price axis
    axv = fig.add_subplot(gs[1, 0], sharex=ax)

    for col, mask in (("#1a8a3a", up), ("#c01616", ~up)):
        idx = np.where(mask)[0]
        ax.vlines(x[idx], l[idx], h[idx], color=col, lw=0.8, zorder=2)
        ax.bar(x[idx], np.abs(c[idx] - o[idx]), bottom=np.minimum(o[idx], c[idx]),
               width=0.65, color=col, zorder=3)
        axv.bar(x[idx], v[idx], width=0.65, color=col, zorder=2)

    # recency-weighted frequency histogram on the right, aligned to price
    axp.barh(centers, weights, height=binh * 0.9, color="#3a6ea5", alpha=0.85)
    for pk in peaks:                                     # mark the profile peaks (candidate bands)
        axp.axhline(pk["price"], color="#d08400", lw=0.8, alpha=0.7)
        ax.axhline(pk["price"], color="#d08400", lw=0.8, ls="--", alpha=0.45, zorder=1)
        ax.annotate(f"{pk['price']:.2f}", xy=(x[-1], pk["price"]), xytext=(4, 0),
                    textcoords="offset points", va="center", fontsize=8, color="#aa6a00")

    ax.set_title(f"{symbol} — last {len(c)} trading days ({dt.iloc[0]:%Y-%m-%d} .. "
                 f"{dt.iloc[-1]:%Y-%m-%d})  close={c[-1]:.2f}   "
                 f"recency-weighted price frequency (halflife {halflife:.0f} bars)",
                 fontsize=12)
    ax.set_ylabel("price"); ax.grid(True, alpha=0.2); ax.margins(x=0.01)
    plt.setp(ax.get_xticklabels(), visible=False)      # volume panel carries the dates
    axp.set_xticks([]); axp.grid(True, axis="y", alpha=0.2)
    axp.set_xlabel("freq (recency-wtd)", fontsize=9)
    plt.setp(axp.get_yticklabels(), visible=False)
    axv.set_ylabel("volume"); axv.grid(True, alpha=0.2)
    axv.yaxis.set_major_formatter(FuncFormatter(
        lambda y, _: f"{y/1e6:.0f}M" if y >= 1e6 else f"{y/1e3:.0f}K"))
    step = max(1, len(c) // 12)
    ticks = list(range(0, len(c), step))
    axv.set_xticks(ticks)
    axv.set_xticklabels([f"{dt.iloc[i]:%Y-%m-%d}" for i in ticks], rotation=45, ha="right")

    out = os.path.join(HERE, f"{symbol}_price_profile.png")
    fig.savefig(out, dpi=130, bbox_inches="tight")
    print(f"wrote {out}  ({len(peaks)} profile peaks)")

    load_env()
    os.environ["EMAIL_RECIPIENT"] = "brandg@gmail.com"
    sys.path.insert(0, os.path.join(REPO, "src"))
    from bluehorseshoe.core.email_service import EmailService
    svc = EmailService()
    if not svc.is_configured():
        print("email NOT configured — PNG written but not sent."); return
    pk_txt = ", ".join(f"{p['price']:.2f}" for p in peaks)
    ok = svc.send(subject=f"{symbol} — price + recency-weighted frequency profile",
                  text_body=(f"{symbol}: last {len(c)} trading days, {dt.iloc[0]:%Y-%m-%d} to "
                             f"{dt.iloc[-1]:%Y-%m-%d}. Close {c[-1]:.2f}. Frequency profile "
                             f"(recency halflife {halflife:.0f} bars). Peaks: {pk_txt}."),
                  attachments=[out])
    print("email sent" if ok else "email send FAILED")


if __name__ == "__main__":
    main()
