"""Combined MNQ+MES+M2K portfolio view for the roll-stitched real-bar opening-range fade.

Runs all three roll-stitched backtests from cache (no re-pull), then pools them (1 contract each,
central cost) to test the diversification thesis: does stacking three index micros smooth the
quarterly variance vs any single instrument? Reports per-quarter P&L per instrument + combined,
the coefficient of variation (std/mean) of quarterly P&L, and the worst quarter vs the average.

    ./run.sh python research/opening_range_fade_v1/combine_portfolio.py
"""
import os, sys, statistics
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
import data as D
from strategy import simulate
from gateway_backtest import contract_windows, ROOT_MULT
from paper_forward import rt_cost

ROOTS = ["MNQ", "MES", "M2K"]


def quarter_pnl(root, ib):
    mult = ROOT_MULT[root]; rt = rt_cost(root, "central")
    byq = defaultdict(float); n = w = 0
    for c, s_, e_ in contract_windows(ib, root):
        for st in D.build_setups([c.localSymbol], day_min=s_, day_max=e_):
            o, pnl = simulate(st, C.BOUNCE_B)
            if o == "NEVER_FILLED":
                continue
            byq[st["_q"]] += pnl * st["U"] * mult - rt
            n += 1; w += (o == "WIN")
    return byq, n, w


def cv(vals):
    m = statistics.mean(vals)
    return statistics.pstdev(vals) / m if m else float("nan"), m


def main():
    from ib_async import IB
    ib = IB(); ib.connect("127.0.0.1", 4004, clientId=84, timeout=10, readonly=True)
    data = {r: quarter_pnl(r, ib) for r in ROOTS}
    ib.disconnect()

    quarters = sorted({q for r in ROOTS for q in data[r][0]})
    print(f"{'quarter':9}" + "".join(f"{r:>10}" for r in ROOTS) + f"{'COMBINED':>11}")
    combined = []
    for q in quarters:
        row = [data[r][0].get(q, 0.0) for r in ROOTS]
        tot = sum(row); combined.append(tot)
        print(f"{q:9}" + "".join(f"{v:>+10.0f}" for v in row) + f"{tot:>+11.0f}")

    print("\n" + "-" * 60)
    for r in ROOTS:
        byq, n, w = data[r]
        vals = [byq.get(q, 0.0) for q in quarters]
        c, m = cv(vals)
        print(f"  {r}: {n:3} trades  win {100*w/n:4.1f}%  total ${sum(vals):+6.0f}  "
              f"mean/q ${m:+5.0f}  CV {c:4.2f}  worst/mean {min(vals)/m:+.2f}")
    c, m = cv(combined)
    n_all = sum(data[r][1] for r in ROOTS); w_all = sum(data[r][2] for r in ROOTS)
    pos = sum(v > 0 for v in combined)
    print(f"  COMBINED: {n_all} trades  win {100*w_all/n_all:.1f}%  total ${sum(combined):+.0f}  "
          f"mean/q ${m:+.0f}  CV {c:.2f}  worst/mean {min(combined)/m:+.2f}  ({pos}/{len(combined)} q+)")
    print(f"\n  Diversification: combined CV {c:.2f} vs single-instrument CVs "
          f"{[round(cv([data[r][0].get(q,0.0) for q in quarters])[0],2) for r in ROOTS]} "
          f"-> lower = smoother risk-adjusted quarterly P&L.")
    print(f"  Throughput: {n_all} fills / 2yr ~= {n_all/2:.0f}/yr (~{n_all/2/252:.1f} trades/day across 3).")


if __name__ == "__main__":
    main()
