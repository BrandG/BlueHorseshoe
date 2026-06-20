"""Dump detected S/R levels + the swing pivots they're built from, with DATES,
so the detector can be checked by eye against a chart.

Usage:
    python dump_levels.py SYMBOL [AS_OF_DATE] [START_DATE]

  SYMBOL      ticker, e.g. AAPL          (default AAPL)
  AS_OF_DATE  YYYY-MM-DD; levels are snapshotted as they stood on this date
              (default = last available bar). Uses nearest bar <= this date.
  START_DATE  history start (default 2015-01-01)

Writes two CSVs next to this script:
  <SYMBOL>_pivots.csv  — every confirmed swing high/low: date, type, price, volume
  <SYMBOL>_levels.csv  — clustered levels active as of AS_OF_DATE: price, side,
                         touches, strength, first/last touch date, distance (ATR),
                         and the dates of every pivot that feeds the level.
"""
import sys, os
import numpy as np, pandas as pd, duckdb

sys.path.insert(0, os.path.dirname(__file__))
from detector import level_snapshot, SRParams  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DB = os.path.join(REPO, "data", "ohlcv.duckdb")


def main():
    symbol = sys.argv[1].upper() if len(sys.argv) > 1 else "AAPL"
    as_of_date = sys.argv[2] if len(sys.argv) > 2 else None
    start = sys.argv[3] if len(sys.argv) > 3 else "2015-01-01"

    con = duckdb.connect(DB, read_only=True)
    d = con.execute(
        "SELECT date,open,high,low,close,volume FROM ohlcv "
        "WHERE symbol=? AND date>=? ORDER BY date", [symbol, start]).df()
    con.close()
    if d.empty:
        print(f"No rows for {symbol} since {start}")
        return

    dates = pd.to_datetime(d.date).dt.strftime("%Y-%m-%d").to_numpy()
    h, l, c, v = (d[x].to_numpy(float) for x in ("high", "low", "close", "volume"))
    n = len(c)

    # resolve as_of bar index (nearest bar on or before the requested date)
    if as_of_date:
        le = np.where(dates <= as_of_date)[0]
        if len(le) == 0:
            print(f"{as_of_date} is before {symbol}'s history starts ({dates[0]})")
            return
        as_of = int(le[-1])
    else:
        as_of = n - 1

    params = SRParams()
    snap, sh, sl, atr = level_snapshot(h, l, c, v, params, as_of=as_of)
    close_at = c[as_of]
    atr_at = atr[as_of]

    # ---- pivots CSV (all confirmed swing highs/lows up to as_of) ----
    piv_rows = []
    k = params.fractal_k
    for i in range(n):
        if i + k > as_of:        # only pivots CONFIRMED by as_of (point-in-time)
            break
        if sh[i]:
            piv_rows.append((dates[i], "high", round(float(h[i]), 4), int(v[i])))
        if sl[i]:
            piv_rows.append((dates[i], "low", round(float(l[i]), 4), int(v[i])))
    piv_df = pd.DataFrame(piv_rows, columns=["date", "type", "price", "volume"])
    piv_path = os.path.join(HERE, f"{symbol}_pivots.csv")
    piv_df.to_csv(piv_path, index=False)

    # ---- levels CSV (clustered, active as of as_of) ----
    lvl_rows = []
    for lv in snap:
        side = "support" if lv["price"] < close_at else "resistance"
        dist_atr = abs(close_at - lv["price"]) / atr_at if atr_at > 0 else np.nan
        member_dates = ";".join(dates[b] for b in sorted(lv["members"]))
        lvl_rows.append((
            round(lv["price"], 4), side, lv["touches"], round(lv["strength"], 3),
            round(dist_atr, 3), dates[lv["first_touch_bar"]],
            dates[lv["last_touch_bar"]], lv["origin"], member_dates,
        ))
    lvl_df = pd.DataFrame(lvl_rows, columns=[
        "price", "side", "touches", "strength", "dist_atr",
        "first_touch", "last_touch", "origin", "member_dates"])
    lvl_path = os.path.join(HERE, f"{symbol}_levels.csv")
    lvl_df.to_csv(lvl_path, index=False)

    # ---- readable printout ----
    print(f"\n{symbol}  —  levels as of {dates[as_of]}  "
          f"(close={close_at:.2f}, ATR={atr_at:.2f})")
    print(f"{len(piv_df)} confirmed swing pivots, {len(lvl_df)} active levels "
          f"(fractal_k={params.fractal_k}, cluster_tol={params.cluster_tol_atr} ATR, "
          f"max_lookback={params.max_lookback} bars)\n")

    show = lvl_df.copy()
    show["price"] = show["price"].map(lambda x: f"{x:.2f}")
    print("ACTIVE LEVELS (sorted by price; nearest-to-price marked »):")
    print(f"  {'price':>9} {'side':>11} {'touch':>5} {'strlength':>8} "
          f"{'distATR':>7} {'last_touch':>11}  member pivot dates")
    # mark nearest support below and nearest resistance above
    sup = lvl_df[lvl_df.side == "support"]
    res = lvl_df[lvl_df.side == "resistance"]
    near_sup = sup.price.max() if len(sup) else None
    near_res = res.price.min() if len(res) else None
    for _, r in lvl_df.iterrows():
        mark = " "
        if r.price == near_sup or r.price == near_res:
            mark = "»"
        md = r.member_dates if len(r.member_dates) < 70 else r.member_dates[:67] + "..."
        print(f"{mark} {r.price:>9.2f} {r.side:>11} {r.touches:>5} "
              f"{r.strength:>8.3f} {r.dist_atr:>7.3f} {r.last_touch:>11}  {md}")

    print(f"\nwrote:\n  {piv_path}\n  {lvl_path}")
    print("\ntip: open the CSVs, or re-run with a past date to see what the lines "
          "looked like then, e.g.")
    print(f"  python {os.path.basename(__file__)} {symbol} 2024-06-01")


if __name__ == "__main__":
    main()
