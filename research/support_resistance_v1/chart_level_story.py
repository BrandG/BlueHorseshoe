"""ONE continuous chart telling the whole story of a pure-support level:
  * the level drawn across the period (starting where it became confirmed),
  * the turn-ups that DEFINE it (green circles, dated),
  * every later APPROACH marked where it happened -- green up-triangle = held/bounced,
    red down-triangle = broke, grey = chop.

So you can see WHERE the line comes from and WHY each test point was chosen, in context.

Usage: python chart_level_story.py [SYMBOL] [N_DAYS] [--email]
"""
import sys, os
import numpy as np, pandas as pd, duckdb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(__file__))
from reversal_profile import cluster_levels                      # noqa: E402
from detector import wilder_atr                                  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DB = os.path.join(REPO, "data", "ohlcv.duckdb")
NEAR = 0.5; APPROACH = 10; GAP = 15; H = 20
STOP_KIND = "atr"        # "atr" (val = ATR multiple) or "pct" (val = fraction below entry)
STOP_VAL = 1.0           # default: stop 1.0 ATR below entry (sane, outside the noise band)
TARGET_MULT = 1.5        # target = entry + TARGET_MULT * (entry-stop) -> 1.5:1 reward:risk
K = 3


def stop_of(entry, a):
    return entry - STOP_VAL * a if STOP_KIND == "atr" else entry * (1 - STOP_VAL)


def stop_label():
    return f"{STOP_VAL:.1f} ATR" if STOP_KIND == "atr" else f"{STOP_VAL:.1%}"


def load_env():
    p = os.path.join(REPO, ".env")
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, val = line.partition("=")
                os.environ.setdefault(k.strip(), val.strip().strip('"').strip("'"))


def bracket_outcome(t, entry, h, l, n, stop_px, target_px):
    """First-touch bracket: stopped (low<=stop) vs won (high>=target), conservative
    (same-bar both -> stopped). 'open' if neither within H bars."""
    end = min(t + H, n - 1)
    for k in range(t + 1, end + 1):
        if l[k] <= stop_px:
            return "stopped"
        if h[k] >= target_px:
            return "won"
    return "open"


def approaches(L, h, l, c, atr, start, n):
    """Bars where price comes within NEAR ATR of level L from above; score as a 1.5:1
    bracket (stop = stop_of(entry, atr)). Returns (bar, entry, stop_px, outcome)."""
    out = []; last = -10**9
    for t in range(start, n - 1):
        a = atr[t]
        d = (c[t] - L) / a
        if d < 0 or d > NEAR:
            continue
        lo = max(0, t - APPROACH)
        if c[lo:t].max() <= L + NEAR * a:        # must have approached from above
            continue
        if t - last < GAP:
            continue
        last = t
        entry = c[t]
        stop_px = stop_of(entry, a)
        target_px = entry + TARGET_MULT * (entry - stop_px)
        oc = bracket_outcome(t, entry, h, l, n, stop_px, target_px) if t + H < n else "open"
        out.append((t, entry, stop_px, oc))
    return out


def main():
    do_email = "--email" in sys.argv
    pos = [a for a in sys.argv[1:] if not a.startswith("--")]
    symbol = (pos[0].upper() if pos else "VZ")
    ndays = int(pos[1]) if len(pos) > 1 else 378           # ~18 months
    if len(pos) > 2:                                        # optional stop override: "1.0atr" or "0.02"
        global STOP_KIND, STOP_VAL
        s = pos[2].lower()
        if s.endswith("atr"):
            STOP_KIND, STOP_VAL = "atr", float(s[:-3])
        else:
            STOP_KIND, STOP_VAL = "pct", float(s)

    con = duckdb.connect(DB, read_only=True)
    d = con.execute("SELECT date,open,high,low,close FROM ohlcv WHERE symbol=? "
                    "ORDER BY date DESC LIMIT ?", [symbol, ndays]).df()
    con.close()
    d = d.iloc[::-1].reset_index(drop=True)
    dts = pd.to_datetime(d.date)
    o, h, l, c = (d[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    n = len(c); x = np.arange(n); up = c >= o
    atr = wilder_atr(h, l, c, 14)
    atr = np.where(np.isnan(atr) | (atr <= 0), np.nanmedian(atr), atr)

    levels, _ = cluster_levels(h, l, c, tol_atr=0.4)
    psup = [L for L in levels if L["character"] == "support"]      # pure-support only
    if not psup:
        print(f"{symbol}: no pure-support levels in window"); return

    fig, ax = plt.subplots(figsize=(18, 9))
    for col, mask in (("#1a8a3a", up), ("#c01616", ~up)):
        idx = np.where(mask)[0]
        ax.vlines(x[idx], l[idx], h[idx], color=col, lw=0.7, alpha=0.8, zorder=2)
        ax.bar(x[idx], np.abs(c[idx] - o[idx]), bottom=np.minimum(o[idx], c[idx]),
               width=0.6, color=col, alpha=0.8, zorder=3)

    tally = {"won": 0, "stopped": 0, "open": 0}
    for L in psup:
        lvl = L["price"]
        tb = sorted(b for b, _, _ in L["members"])
        confirm = tb[K - 1] + K if len(tb) >= K else tb[-1] + K   # 3rd turn-up known
        confirm = min(confirm, n - 1)
        ax.hlines(lvl, confirm, n - 1, color="#1a4fa0", lw=2.0, zorder=4)
        ax.annotate(f"support {lvl:.2f}  ({L['touches']} turn-ups)", xy=(n - 1, lvl),
                    xytext=(6, 0), textcoords="offset points", va="center",
                    fontsize=9, color="#1a4fa0", fontweight="bold")
        for b, p, _ in L["members"]:                               # the defining turn-ups
            ax.scatter(b, p, s=55, facecolor="none", edgecolor="#1a8a3a", lw=1.8, zorder=6)
        for (t, entry, stop_px, oc) in approaches(lvl, h, l, c, atr, confirm, n):
            tally[oc] = tally.get(oc, 0) + 1
            mk = {"won": ("^", "#1a8a3a"), "stopped": ("v", "#c01616"),
                  "open": ("D", "#888")}[oc]
            end = min(t + H, n - 1)
            ax.hlines(stop_px, t, end, color="#c01616", ls=(0, (2, 2)), lw=1.0, alpha=0.8, zorder=5)
            ax.scatter(t, entry, marker=mk[0], s=120, color=mk[1], edgecolor="white",
                       lw=1.0, zorder=7)

    # legend + readable date axis
    from matplotlib.lines import Line2D
    leg = [Line2D([0], [0], color="#1a4fa0", lw=2, label="pure-support level"),
           Line2D([0], [0], marker="o", color="w", markerfacecolor="none",
                  markeredgecolor="#1a8a3a", label="defining turn-up", markersize=9),
           Line2D([0], [0], color="#c01616", ls=(0, (2, 2)), lw=1, label=f"stop ({stop_label()} below entry)"),
           Line2D([0], [0], marker="^", color="w", markerfacecolor="#1a8a3a", label="won (+1.5R target first)", markersize=11),
           Line2D([0], [0], marker="v", color="w", markerfacecolor="#c01616", label="stopped (stop hit first)", markersize=11),
           Line2D([0], [0], marker="D", color="w", markerfacecolor="#888", label="open (neither in 20 bars)", markersize=9)]
    ax.legend(handles=leg, fontsize=9, loc="best", framealpha=0.9)
    step = max(1, n // 14)
    ax.set_xticks(range(0, n, step))
    ax.set_xticklabels([f"{dts.iloc[i]:%Y-%m-%d}" for i in range(0, n, step)], rotation=45, ha="right")
    ax.set_ylabel("price"); ax.grid(True, alpha=0.2); ax.margins(x=0.01)
    ax.set_title(f"{symbol} — pure-support as 1.5:1 bracket (stop {stop_label()} below entry)  "
                 f"({dts.iloc[0]:%Y-%m-%d} .. {dts.iloc[-1]:%Y-%m-%d}):  "
                 f"won {tally['won']} / stopped {tally['stopped']} / open {tally['open']}", fontsize=11)
    fig.tight_layout()
    out = os.path.join(HERE, f"{symbol}_level_story.png")
    fig.savefig(out, dpi=130)
    print(f"wrote {out}  (pure-support levels: {[round(L['price'],2) for L in psup]}; tests {tally})")

    if do_email:
        load_env(); os.environ["EMAIL_RECIPIENT"] = "brandg@gmail.com"
        sys.path.insert(0, os.path.join(REPO, "src"))
        from bluehorseshoe.core.email_service import EmailService
        svc = EmailService()
        if svc.is_configured():
            ok = svc.send(subject=f"{symbol} — pure-support level story (1.5:1 bracket, {stop_label()} stop)",
                          text_body=(f"{symbol}: pure-support levels; green circles = defining turn-ups; "
                                     f"each later approach scored as a 1.5:1 bracket (stop {stop_label()} below "
                                     f"entry, red dashed line). green ^ = won, red v = stopped, grey diamond = "
                                     f"open. won {tally['won']} / stopped {tally['stopped']} / open {tally['open']}."),
                          attachments=[out])
            print("email sent" if ok else "email FAILED")


if __name__ == "__main__":
    main()
