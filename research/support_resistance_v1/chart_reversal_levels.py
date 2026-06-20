"""Candle chart + DIRECT reversal-point levels (Brand's >=3-touch clustering).

Levels come from clustering reversal turning points with a tight tolerance (not from a
smoothed histogram peak), so close neighbors stay separate and sharp few-touch extremes
and old-but-real bands both survive. Band line weight ~ strength (recency x swing depth);
green = support / red = resistance vs today's close; touch dots circled. Price regions
holding several stacked bands are shaded as reinforced ZONES. Histogram sidebar kept for
context.

Usage: python chart_reversal_levels.py [SYMBOL] [N_DAYS] [TOL_ATR] [--email]
"""
import sys, os
import numpy as np, pandas as pd, duckdb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(__file__))
from reversal_profile import build_reversal_profile, cluster_levels, find_zones  # noqa: E402

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
    tol = float(pos[2]) if len(pos) > 2 else 0.4

    con = duckdb.connect(DB, read_only=True)
    d = con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? "
                    "ORDER BY date DESC LIMIT ?", [symbol, ndays]).df()
    con.close()
    d = d.iloc[::-1].reset_index(drop=True)
    dt = pd.to_datetime(d.date)
    o, h, l, c, v = (d[x].to_numpy(float) for x in ("open", "high", "low", "close", "volume"))
    x = np.arange(len(c)); upm = c >= o; n = len(c)

    levels, atr = cluster_levels(h, l, c, tol_atr=tol)
    zones = find_zones(levels, atr, zone_atr=0.8)
    centers, prof, pivots, _ = build_reversal_profile(h, l, c, v)
    binh = (centers[1] - centers[0]) if len(centers) > 1 else atr * 0.25
    smax = max((L["strength"] for L in levels), default=1.0) or 1.0

    fig = plt.figure(figsize=(16, 9))
    gs = fig.add_gridspec(1, 2, width_ratios=[5, 1], wspace=0.02)
    ax = fig.add_subplot(gs[0, 0]); axp = fig.add_subplot(gs[0, 1], sharey=ax)

    for zn in zones:                                  # reinforced zones behind everything
        ax.axhspan(zn["lo"], zn["hi"], color="#f2c200", alpha=0.12, zorder=0)
    for col, mask in (("#1a8a3a", upm), ("#c01616", ~upm)):
        idx = np.where(mask)[0]
        ax.vlines(x[idx], l[idx], h[idx], color=col, lw=0.8, zorder=2)
        ax.bar(x[idx], np.abs(c[idx] - o[idx]), bottom=np.minimum(o[idx], c[idx]),
               width=0.6, color=col, zorder=3)

    CHAR_COL = {"support": "#1a8a3a", "resistance": "#c01616", "flip": "#8e44ad"}
    close_now = c[-1]
    ax.axhline(close_now, color="#444", ls=":", lw=1.0, alpha=0.7, zorder=4)
    for L in levels:
        col = CHAR_COL[L["character"]]
        is_flip = L["character"] == "flip"
        lw = 1.0 + 3.5 * (L["strength"] / smax)
        ax.axhline(L["price"], color=col, lw=lw, alpha=0.7 if is_flip else 0.45,
                   zorder=5 if is_flip else 4)
        # touch dots: hollow=turn-up (support touch), filled=turn-down (resistance touch)
        for (b, p, kd) in L["members"]:
            ax.scatter(b, p, s=30, facecolor=(col if kd == "R" else "none"),
                       edgecolor=col, lw=1.3, zorder=6)
        star = " *" if is_flip else ""
        ax.annotate(f"{L['price']:.2f}  {L['n_down']}↓/{L['n_up']}↑{star}",
                    xy=(n - 1, L["price"]), xytext=(4, 0), textcoords="offset points",
                    va="center", fontsize=8, color=col, fontweight=("bold" if is_flip else "normal"))
        # actionability vs today's price as a SEPARATE left-edge marker (not the line color)
        ax.annotate("▲" if L["actionable"] == "buy-zone" else "▼",
                    xy=(0, L["price"]), xytext=(-12, 0), textcoords="offset points",
                    va="center", ha="center", fontsize=7,
                    color=("#1a8a3a" if L["actionable"] == "buy-zone" else "#c01616"))

    axp.barh(centers, prof, height=binh * 0.9, color="#3a6ea5", alpha=0.8)
    for L in levels:
        axp.axhline(L["price"], color=CHAR_COL[L["character"]], lw=0.8, alpha=0.6)

    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D
    legend = [Patch(color="#1a8a3a", label="support (only turn-ups)"),
              Patch(color="#c01616", label="resistance (only turn-downs)"),
              Patch(color="#8e44ad", label="flip * (both sides)"),
              Line2D([0], [0], marker="^", color="w", markerfacecolor="#1a8a3a",
                     label="▲ buy-zone (below price)", markersize=8),
              Line2D([0], [0], marker="v", color="w", markerfacecolor="#c01616",
                     label="▼ stall-zone (above price)", markersize=8)]
    ax.legend(handles=legend, fontsize=7, loc="lower right", framealpha=0.9)

    zt = "; ".join(f"{z['lo']:.1f}-{z['hi']:.1f}" for z in zones) or "none"
    nflip = sum(1 for L in levels if L["character"] == "flip")
    ax.set_title(f"{symbol} — reversal levels by character (>=3 touches, tol {tol} ATR): "
                 f"{len(levels)} bands, {nflip} flips, zones[{zt}]  close={c[-1]:.2f}", fontsize=12)
    ax.set_ylabel("price"); ax.grid(True, alpha=0.2); ax.margins(x=0.01)
    axp.set_xticks([]); axp.grid(True, axis="y", alpha=0.2)
    plt.setp(axp.get_yticklabels(), visible=False)
    step = max(1, n // 12)
    ax.set_xticks(range(0, n, step))
    ax.set_xticklabels([f"{dt.iloc[i]:%Y-%m-%d}" for i in range(0, n, step)], rotation=45, ha="right")

    out = os.path.join(HERE, f"{symbol}_reversal_levels.png")
    fig.savefig(out, dpi=130, bbox_inches="tight")
    print(f"wrote {out}  ({len(levels)} levels: {[round(L['price'],2) for L in levels]}; zones {zt})")

    if do_email:
        load_env(); os.environ["EMAIL_RECIPIENT"] = "brandg@gmail.com"
        sys.path.insert(0, os.path.join(REPO, "src"))
        from bluehorseshoe.core.email_service import EmailService
        svc = EmailService()
        if svc.is_configured():
            lv = ", ".join(f"{L['price']:.2f}({L['n_down']}d/{L['n_up']}u,{L['character']})" for L in levels)
            flips = ", ".join(f"{L['price']:.2f}" for L in levels if L["character"] == "flip")
            ok = svc.send(subject=f"{symbol} — reversal levels by character (flips highlighted)",
                          text_body=(f"{symbol}: {len(levels)} bands -> {lv}. FLIP levels (respected "
                                     f"both sides, strongest): {flips}. Shaded = reinforced zones: {zt}. "
                                     f"Color=character (green support/red resistance/purple flip); "
                                     f"edge ▲▼=buy/stall vs today. Tol {tol} ATR."),
                          attachments=[out])
            print("email sent" if ok else "email FAILED")


if __name__ == "__main__":
    main()
