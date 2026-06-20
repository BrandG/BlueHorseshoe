"""Event gallery, scored as a 1.5:1 bracket with a 1-ATR stop (sane, outside the noise).

For each PIT pure-support approach across the range-bound universe: enter at the approach
close, stop 1 ATR below, target 1.5x the stop distance above. Outcome = won / stopped /
open. Real win/stop rate + expectancy reported up top; then equal numbers of WON and STOPPED
shown side by side (full price+date axes, the stop drawn) so the eye can hunt for what
separates a hold from a stop-out under a realistic stop.

Usage: python chart_gallery.py [--email]
"""
import sys, os
import numpy as np, pandas as pd, duckdb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(__file__))
from reversal_profile import build_pivots, cluster_pivots       # noqa: E402
from detector import wilder_atr                                  # noqa: E402
from detector_v3 import range_score                             # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DB = os.path.join(REPO, "data", "ohlcv.duckdb")
START = "2016-01-01"; ER_MAX = 0.11
WARMUP = 80; WIN_BEFORE, WIN_AFTER = 25, 20
NEAR = 0.5; APPROACH = 10; GAP = 15; H = 20
STOP_ATR = 1.0; TARGET_MULT = 1.5     # stop 1 ATR below entry; target = 1.5x stop distance
N_EACH = 3


def load_env():
    p = os.path.join(REPO, ".env")
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, val = line.partition("=")
                os.environ.setdefault(k.strip(), val.strip().strip('"').strip("'"))


def score(t, entry, stop_px, h, l, c, n):
    tgt = entry + TARGET_MULT * (entry - stop_px)
    end = min(t + H, n - 1)
    for k in range(t + 1, end + 1):
        if l[k] <= stop_px:
            return "stopped", -1.0
        if h[k] >= tgt:
            return "won", TARGET_MULT
    return "open", (c[end] - entry) / (entry - stop_px)


def collect(universe, con):
    events = []; sumR = 0.0; nR = 0
    for sym in universe:
        d = con.execute("SELECT date,open,high,low,close FROM ohlcv WHERE symbol=? AND date>=? "
                        "ORDER BY date", [sym, START]).df()
        dts = pd.to_datetime(d.date).dt.strftime("%Y-%m-%d").to_numpy()
        o, h, l, c = (d[x].to_numpy(float) for x in ("open", "high", "low", "close"))
        n = len(c)
        if n < WARMUP + H + 5:
            continue
        atr = wilder_atr(h, l, c, 14)
        atr = np.where(np.isnan(atr) | (atr <= 0), np.nanmedian(atr), atr)
        pivots = build_pivots(h, l, 3)
        last = -10**9
        for t in range(WARMUP, n - H):
            a = atr[t]
            levels, _ = cluster_pivots(pivots, atr, c, as_of=t)
            ps = [L for L in levels if L["character"] == "support" and L["price"] < c[t]]
            if not ps:
                continue
            near = max(ps, key=lambda L: L["price"])
            if (c[t] - near["price"]) / a > NEAR:
                continue
            lo = max(0, t - APPROACH)
            if c[lo:t].max() <= near["price"] + NEAR * a:
                continue
            if t - last < GAP:
                continue
            last = t
            entry = c[t]; stop_px = entry - STOP_ATR * a
            oc, R = score(t, entry, stop_px, h, l, c, n)
            sumR += R; nR += 1
            w0 = max(0, t - WIN_BEFORE); w1 = min(n, t + WIN_AFTER + 1)
            events.append({
                "sym": sym, "date": dts[t], "outcome": oc, "R": R, "level": near["price"],
                "entry": entry, "stop": stop_px, "ntouch": near["touches"],
                "h": h[w0:w1], "l": l[w0:w1], "c": c[w0:w1], "dates": dts[w0:w1], "ai": t - w0,
                "touch": [(b - w0, p) for (b, p, kd) in near["members"] if w0 <= b < w1],
            })
    return events, (sumR / nR if nR else float("nan"))


def draw_panel(ax, ev):
    n = len(ev["c"]); x = np.arange(n); ai = ev["ai"]
    oc = {"won": "#1a8a3a", "stopped": "#c01616", "open": "#888"}[ev["outcome"]]
    ax.axvspan(ai, n - 1, color="#f7f7f7", zorder=0)
    ax.fill_between(x, ev["l"], ev["h"], color="#bcd", alpha=0.55, zorder=1)
    ax.plot(x, ev["c"], color="#222", lw=1.1, zorder=2)
    ax.axhline(ev["level"], color="#1a4fa0", lw=1.8, zorder=3)
    ax.axhline(ev["stop"], color="#c01616", ls=(0, (3, 3)), lw=1.2, zorder=3)
    ax.annotate(f"support {ev['level']:.2f}", xy=(0, ev["level"]), xytext=(3, 3),
                textcoords="offset points", fontsize=8, color="#1a4fa0", va="bottom", fontweight="bold")
    ax.annotate("stop (1 ATR)", xy=(0, ev["stop"]), xytext=(3, -10),
                textcoords="offset points", fontsize=7, color="#c01616", va="top")
    ax.axvline(ai, color="#444", ls=":", lw=1.2, zorder=3)
    ax.scatter(ai, ev["entry"], s=70, color=oc, edgecolor="white", lw=1.0, zorder=6)
    for bi, p in ev["touch"]:
        ax.scatter(bi, p, s=34, facecolor="none", edgecolor="#1a8a3a", lw=1.4, zorder=5)
    dates = ev["dates"]; ticks = sorted({0, ai, n - 1})
    ax.set_xticks(ticks); ax.set_xticklabels([dates[i] for i in ticks], fontsize=7)
    ax.tick_params(axis="y", labelsize=7); ax.set_ylabel("price", fontsize=7)
    ax.grid(True, alpha=0.15)
    ax.set_title(f"{ev['sym']}  ·  {ev['date']}  ·  {ev['outcome'].upper()} ({ev['R']:+.1f}R)\n"
                 f"entry {ev['entry']:.2f} at support {ev['level']:.2f} ({ev['ntouch']} turn-ups)",
                 fontsize=8.5, color=oc)
    for s in ax.spines.values():
        s.set_color(oc); s.set_linewidth(2.0)


def main():
    do_email = "--email" in sys.argv
    con = duckdb.connect(DB, read_only=True)
    cand = [s.strip() for s in open(os.path.join(HERE, "symbols.txt"))]
    universe = []
    for s in cand:
        d = con.execute("SELECT close,volume FROM ohlcv WHERE symbol=? AND date>=? ORDER BY date",
                        [s, START]).df()
        c = d.close.to_numpy(float); v = d.volume.to_numpy(float)
        if len(c) < 900 or not (5 <= c[-1] <= 500):
            continue
        if np.median(c[-120:] * v[-120:]) < 3e6:
            continue
        rs = range_score(c)
        if not np.isnan(rs) and rs <= ER_MAX:
            universe.append(s)
    events, expR = collect(universe, con)
    con.close()

    nN = len(events)
    won = [e for e in events if e["outcome"] == "won"]
    stp = [e for e in events if e["outcome"] == "stopped"]
    opn = [e for e in events if e["outcome"] == "open"]
    head = (f"Pure-support, 1.5:1 bracket, 1-ATR stop (n={nN}): won {len(won)/nN:.0%} / "
            f"stopped {len(stp)/nN:.0%} / open {len(opn)/nN:.0%}  ->  expectancy {expR:+.3f} R/trade")
    print(head)

    rng = np.random.default_rng(7)
    pick_w = [won[i] for i in rng.choice(len(won), min(N_EACH, len(won)), replace=False)]
    pick_s = [stp[i] for i in rng.choice(len(stp), min(N_EACH, len(stp)), replace=False)]

    fig, axes = plt.subplots(2, 3, figsize=(19, 11))
    fig.suptitle(head + "\nBlue = pure-support level · red dashed = 1-ATR stop · green ○ = defining "
                 "turn-ups · shaded = forward 20 bars.   Row 1 = WON, Row 2 = STOPPED (random samples).",
                 fontsize=11)
    for i in range(3):
        draw_panel(axes[0, i], pick_w[i]) if i < len(pick_w) else axes[0, i].axis("off")
        draw_panel(axes[1, i], pick_s[i]) if i < len(pick_s) else axes[1, i].axis("off")
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    out = os.path.join(HERE, "pure_support_gallery.png")
    fig.savefig(out, dpi=130)
    print(f"wrote {out}")

    if do_email:
        load_env(); os.environ["EMAIL_RECIPIENT"] = "brandg@gmail.com"
        sys.path.insert(0, os.path.join(REPO, "src"))
        from bluehorseshoe.core.email_service import EmailService
        guid = EmailService().send(subject="Pure-support gallery (1-ATR bracket: wins vs stops)",
                                   text_body=head + " Row 1 won, row 2 stopped. Blue=level, red "
                                   "dashed=1-ATR stop, shaded=forward 20 bars.",
                                   attachments=[out])
        print("GUID:", guid)


if __name__ == "__main__":
    main()
