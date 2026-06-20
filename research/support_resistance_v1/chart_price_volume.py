"""Plain price + volume chart for one symbol's last year — no S/R overlay, no model.
Just the raw picture, emailed to Brand (headless box, can't view images locally).

Usage: python chart_price_volume.py [SYMBOL] [N_DAYS]
Defaults: SYMBOL=AAPL, N_DAYS=252 (~1 trading year). Candles + daily volume panel.
"""
import sys, os
import numpy as np, pandas as pd, duckdb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DB = os.path.join(REPO, "data", "ohlcv.duckdb")


def load_env():
    """Load repo-root .env into os.environ so EmailService finds SMTP creds."""
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
    symbol = (sys.argv[1].upper() if len(sys.argv) > 1 else "AAPL")
    ndays = int(sys.argv[2]) if len(sys.argv) > 2 else 252

    con = duckdb.connect(DB, read_only=True)
    d = con.execute("SELECT date,open,high,low,close,volume FROM ohlcv WHERE symbol=? "
                    "ORDER BY date DESC LIMIT ?", [symbol, ndays]).df()
    con.close()
    if d.empty:
        print(f"No rows for {symbol}"); return
    d = d.iloc[::-1].reset_index(drop=True)                      # back to chronological
    dt = pd.to_datetime(d.date)
    o, h, l, c, v = (d[x].to_numpy(float) for x in ("open", "high", "low", "close", "volume"))
    x = np.arange(len(c))                                        # index x -> no weekend gaps
    up = c >= o

    fig, (ax, axv) = plt.subplots(2, 1, figsize=(15, 9), sharex=True,
                                  gridspec_kw={"height_ratios": [3, 1], "hspace": 0.05})

    # candlesticks: wick = high-low, body = open-close
    for col, mask in (("#1a8a3a", up), ("#c01616", ~up)):
        idx = np.where(mask)[0]
        ax.vlines(x[idx], l[idx], h[idx], color=col, lw=0.8, zorder=2)
        ax.bar(x[idx], np.abs(c[idx] - o[idx]), bottom=np.minimum(o[idx], c[idx]),
               width=0.65, color=col, zorder=3)
        axv.bar(x[idx], v[idx], width=0.65, color=col, zorder=2)

    ax.set_title(f"{symbol} — last {len(c)} trading days "
                 f"({dt.iloc[0]:%Y-%m-%d} .. {dt.iloc[-1]:%Y-%m-%d})   close={c[-1]:.2f}",
                 fontsize=13)
    ax.set_ylabel("price")
    ax.grid(True, alpha=0.2)
    axv.set_ylabel("volume")
    axv.grid(True, alpha=0.2)
    axv.yaxis.set_major_formatter(FuncFormatter(
        lambda y, _: f"{y/1e6:.0f}M" if y >= 1e6 else f"{y/1e3:.0f}K"))

    # sparse date ticks from the index
    step = max(1, len(c) // 12)
    ticks = list(range(0, len(c), step))
    axv.set_xticks(ticks)
    axv.set_xticklabels([f"{dt.iloc[i]:%Y-%m-%d}" for i in ticks], rotation=45, ha="right")
    ax.margins(x=0.01)

    fig.tight_layout()
    out = os.path.join(HERE, f"{symbol}_price_volume.png")
    fig.savefig(out, dpi=130)
    print(f"wrote {out}")

    load_env()
    os.environ["EMAIL_RECIPIENT"] = "brandg@gmail.com"
    sys.path.insert(0, os.path.join(REPO, "src"))
    from bluehorseshoe.core.email_service import EmailService
    svc = EmailService()
    if not svc.is_configured():
        print("email NOT configured — PNG written but not sent."); return
    ok = svc.send(subject=f"{symbol} — last year price + volume",
                  text_body=(f"{symbol}: last {len(c)} trading days, "
                             f"{dt.iloc[0]:%Y-%m-%d} to {dt.iloc[-1]:%Y-%m-%d}. "
                             f"Close {c[-1]:.2f}. Chart attached."),
                  attachments=[out])
    print("email sent" if ok else "email send FAILED")


if __name__ == "__main__":
    main()
