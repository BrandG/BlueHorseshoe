"""Clean, labeled dump of v3 (shelf/magnet/polarity-agnostic) S/R levels.

Usage:
    python dump_levels_v3.py SYMBOL [AS_OF_DATE] [START]
Defaults: SYMBOL=AAPL, AS_OF=last bar, START=2015-01-01.

Prints a labeled table of the confirmed levels in force as of AS_OF_DATE and writes
<SYMBOL>_levels_v3.csv next to this script.
"""
import sys, os
import numpy as np, pandas as pd, duckdb

sys.path.insert(0, os.path.dirname(__file__))
from detector_v3 import detect, active_levels, range_score, SRParamsV3  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(os.path.abspath(os.path.join(HERE, "..", "..")), "data", "ohlcv.duckdb")


def main():
    symbol = sys.argv[1].upper() if len(sys.argv) > 1 else "AAPL"
    as_of_date = sys.argv[2] if len(sys.argv) > 2 else None
    start = sys.argv[3] if len(sys.argv) > 3 else "2015-01-01"
    params = SRParamsV3()

    con = duckdb.connect(DB, read_only=True)
    d = con.execute("SELECT date,high,low,close FROM ohlcv WHERE symbol=? AND date>=? "
                    "ORDER BY date", [symbol, start]).df()
    con.close()
    if d.empty:
        print(f"No rows for {symbol} since {start}"); return

    dates = pd.to_datetime(d.date).dt.strftime("%Y-%m-%d").to_numpy()
    h, l, c = (d[x].to_numpy(float) for x in ("high", "low", "close"))
    n = len(c)
    if as_of_date:
        le = np.where(dates <= as_of_date)[0]
        if len(le) == 0:
            print(f"{as_of_date} precedes {symbol} history ({dates[0]})"); return
        as_of = int(le[-1])
    else:
        as_of = n - 1

    clusters, atr = detect(h, l, c, params)
    live = active_levels(clusters, as_of, params, atr)
    close_at = c[as_of]
    a_at = atr[as_of]
    rs = range_score(c)

    rows = []
    for v in live:
        role = "support" if v.center < close_at else "resistance"
        dist_atr = abs(close_at - v.center) / a_at if a_at > 0 else np.nan
        rows.append(dict(
            price=round(v.center, 2),
            role_now=role,
            dist_ATR=round(dist_atr, 2),
            touches=v.touches,
            as_support=v.up_touches,
            as_resistance=v.down_touches,
            strength=round(v.strength, 2),
            first_touch=dates[v.first_bar],
            last_touch=dates[v.last_bar],
            touch_dates=";".join(dates[b] for b in v.touch_bars),
        ))
    df = pd.DataFrame(rows).sort_values("strength", ascending=False)
    out = os.path.join(HERE, f"{symbol}_levels_v3.csv")
    df.to_csv(out, index=False)

    band = "range-bound" if rs < 0.10 else ("trending" if rs > 0.13 else "mixed")
    print(f"\n{symbol}  —  confirmed S/R levels as of {dates[as_of]}")
    print(f"close = {close_at:.2f} | ATR = {a_at:.2f} | range_score(ER) = {rs:.3f} ({band})")
    print(f"{len(df)} confirmed levels (a level = a price the stock formed a flat shelf at, "
          f"then left, >= {params.min_touches} times)\n")
    print("COLUMNS: price=the level | role_now=is it below(support)/above(resistance) "
          "the current price | dist_ATR=distance from now in ATRs |")
    print("         touches=total tests | as_support/as_resistance=how many tests bounced "
          "up vs down off it | strength=magnitude x recency | dates of every test\n")

    hdr = f"{'price':>8} {'role_now':>11} {'distATR':>7} {'tch':>3} {'asSup':>5} {'asRes':>5} {'strength':>8}  touch_dates"
    print(hdr)
    print("-" * len(hdr))
    for _, r in df.iterrows():
        td = r.touch_dates if len(r.touch_dates) <= 78 else r.touch_dates[:75] + "..."
        print(f"{r.price:>8.2f} {r.role_now:>11} {r.dist_ATR:>7.2f} {r.touches:>3} "
              f"{r.as_support:>5} {r.as_resistance:>5} {r.strength:>8.2f}  {td}")
    print(f"\nfull list with all dates -> {out}")
    print(f"see a past date: python {os.path.basename(__file__)} {symbol} 2025-01-15")


if __name__ == "__main__":
    main()
