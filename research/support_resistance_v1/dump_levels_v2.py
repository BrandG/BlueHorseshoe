"""Dump rejection-confirmed (v2) S/R levels with DATES, for eyeball checking.

Uses detector_v2 (anchor -> depart >=D ATR -> retest; wick touches; vol-weighted
center; body-close invalidation). Lists the levels with the dates of every touch
so each can be verified against a chart.

Usage:
    python dump_levels_v2.py SYMBOL [AS_OF_DATE] [START]
Defaults: SYMBOL=AAPL, AS_OF=last bar, START=2015-01-01.
Params here: width=0.15 ATR, min_bars_between=5 (the rest are SRParamsV2 defaults,
printed below so you can see exactly what produced these).
"""
import sys, os
import numpy as np, pandas as pd, duckdb

sys.path.insert(0, os.path.dirname(__file__))
from detector_v2 import detect_zones, active_levels, SRParamsV2  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(os.path.abspath(os.path.join(HERE, "..", "..")), "data", "ohlcv.duckdb")


def main():
    symbol = sys.argv[1].upper() if len(sys.argv) > 1 else "AAPL"
    as_of_date = sys.argv[2] if len(sys.argv) > 2 else None
    start = sys.argv[3] if len(sys.argv) > 3 else "2015-01-01"

    # >>> the parameters you asked for <<<
    params = SRParamsV2(width_mode="atr", width_atr=0.15, min_bars_between=5)

    con = duckdb.connect(DB, read_only=True)
    d = con.execute("SELECT date,open,high,low,close,volume FROM ohlcv "
                    "WHERE symbol=? AND date>=? ORDER BY date", [symbol, start]).df()
    con.close()
    if d.empty:
        print(f"No rows for {symbol} since {start}"); return

    dates = pd.to_datetime(d.date).dt.strftime("%Y-%m-%d").to_numpy()
    h, l, c, v = (d[x].to_numpy(float) for x in ("high", "low", "close", "volume"))
    n = len(c)
    if as_of_date:
        le = np.where(dates <= as_of_date)[0]
        if len(le) == 0:
            print(f"{as_of_date} precedes {symbol} history ({dates[0]})"); return
        as_of = int(le[-1])
    else:
        as_of = n - 1

    zones, st = detect_zones(h, l, c, v, params)
    close_at = c[as_of]

    print(f"\n{symbol} — rejection-confirmed S/R as of {dates[as_of]}  (close={close_at:.2f})")
    print(f"params: width={params.width_atr} ATR, min_bars_between={params.min_bars_between}, "
          f"breakaway_depth={params.breakaway_depth_atr} ATR, min_touches={params.min_touches}, "
          f"invalidation_confirm_bars={params.invalidation_confirm_bars}, max_age={params.max_age_bars}")
    rr = st["tests_respected"] / max(st["tests_respected"] + st["tests_broken"], 1)
    print(f"history: {st['n_zones']} candidates -> {st['n_confirmed']} confirmed; "
          f"respect_rate={rr:.2f}\n")

    # ---- (A) currently-active confirmed levels (point-in-time as of as_of) ----
    live = active_levels(zones, as_of)
    rows = []
    for vw in sorted(live, key=lambda z: z.center):
        side = "support" if vw.center < close_at else "resistance"
        # ATR at as_of for distance reporting
        rows.append(dict(
            price=round(vw.center, 2), side=side, touches=vw.touches,
            confirmed=dates[vw.confirmed_bar],
            first_touch=dates[min(vw.touch_bars)], last_touch=dates[max(vw.touch_bars)],
            touch_dates=";".join(dates[b] for b in sorted(vw.touch_bars))))
    A = pd.DataFrame(rows)
    pathA = os.path.join(HERE, f"{symbol}_levels_v2_active.csv")
    A.to_csv(pathA, index=False)

    print(f"ACTIVE CONFIRMED LEVELS ({len(A)}), sorted by price:")
    if len(A):
        for _, r in A.iterrows():
            print(f"  {r.price:>9.2f}  {r.side:<11} touches={r.touches}  "
                  f"confirmed={r.confirmed}  | {r.touch_dates}")
    else:
        print("  (none active)")

    # ---- (B) every confirmed level over full history, with lifecycle ----
    allrows = []
    for z in zones:
        if z.confirmed_bar is None:
            continue
        allrows.append(dict(
            anchor=dates[z.anchor_bar],
            side_origin=z.side,
            price=round(z.center, 2),
            touches=len(z.touch_bars),
            confirmed=dates[z.confirmed_bar],
            died=dates[z.death_bar] if z.death_bar is not None else "",
            death_reason=z.death_reason,
            touch_dates=";".join(dates[b] for b in z.touch_bars)))
    B = pd.DataFrame(allrows).sort_values("confirmed")
    pathB = os.path.join(HERE, f"{symbol}_levels_v2_all.csv")
    B.to_csv(pathB, index=False)

    print(f"\nwrote:\n  {pathA}  ({len(A)} active)\n  {pathB}  ({len(B)} confirmed over full history)")
    print(f"\nrun another: python {os.path.basename(__file__)} TICKER [YYYY-MM-DD]")


if __name__ == "__main__":
    main()
