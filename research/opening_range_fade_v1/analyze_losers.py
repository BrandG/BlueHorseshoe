"""Diagnose WHY the roll-stitched real-MNQ backtest lost in 2024Q4 and 2026Q1.

Pure cache (no re-pull beyond one cheap contract-calendar call). For every real trade it reuses
the exact backtest machinery (gateway_backtest windows + build_setups per contract), then enriches
each trade with:
  - side / outcome / pnl (U)
  - efficiency ratio (ER) of the 09:30-11:00 tape: |net move| / sum|bar moves|  (1=trend, 0=chop)
  - run-through: did price break the faded extreme by >1U after the open (the fade got steamrolled)
and aggregates per quarter, split by side, so a trending-tape / one-sided failure is visible.

    ./run.sh python research/opening_range_fade_v1/analyze_losers.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
import data as D
from strategy import simulate
from gateway_backtest import contract_windows, ROOT_MULT
from paper_forward import rt_cost

ROOT = "MNQ"
MULT = ROOT_MULT[ROOT]
RT = rt_cost(ROOT, "central")


def efficiency_ratio(sim):
    """|last_close - first_open| / sum|close-to-close| over the trade window. 1=trend, ~0=chop."""
    if len(sim) < 2:
        return 0.0
    moves = sum(abs(sim[i][4] - sim[i - 1][4]) for i in range(1, len(sim)))
    net = abs(sim[-1][4] - sim[0][1])
    return net / moves if moves else 0.0


def enrich(s):
    """Per-trade record with regime context. s is a built setup (has side/entry/U/sim/L15/H15)."""
    outcome, pnl = simulate(s, C.BOUNCE_B)
    sim = s["sim"]
    # how far past the faded extreme did price run, in U (the steamroll depth)
    if s["side"] == "LONG":               # faded the low; run-through = how far below L15
        depth = (s["L15"] - min(b[3] for b in sim)) / s["U"]
    else:                                  # faded the high; run-through = how far above H15
        depth = (max(b[2] for b in sim) - s["H15"]) / s["U"]
    return dict(side=s["side"], outcome=outcome, pnl=pnl, er=efficiency_ratio(sim),
                run_through=depth, net=(pnl * s["U"] * MULT - RT) if outcome != "NEVER_FILLED" else 0.0)


def main():
    from ib_async import IB
    ib = IB(); ib.connect("127.0.0.1", 4004, clientId=82, timeout=10, readonly=True)
    wins = contract_windows(ib, ROOT); ib.disconnect()

    trades = []  # (day, q, rec)
    for c, s_, e_ in wins:
        for st in D.build_setups([c.localSymbol], day_min=s_, day_max=e_):
            r = enrich(st)
            if r["outcome"] == "NEVER_FILLED":
                continue
            trades.append((st["_day"], st["_q"], r))

    quarters = sorted({q for _, q, _ in trades})
    print(f"{'quarter':8}{'n':>4}{'win%':>6}{'net$':>8}{'LONGw%':>8}{'SHORTw%':>9}"
          f"{'meanER':>8}{'run>1U%':>9}")
    for q in quarters:
        ts = [r for d, qq, r in trades if qq == q]
        L = [r for r in ts if r["side"] == "LONG"]; S = [r for r in ts if r["side"] == "SHORT"]
        wr = lambda g: 100 * sum(x["outcome"] == "WIN" for x in g) / len(g) if g else 0
        runover = 100 * sum(r["run_through"] > 1.0 for r in ts) / len(ts)
        print(f"{q:8}{len(ts):>4}{wr(ts):>6.0f}{sum(r['net'] for r in ts):>8.0f}"
              f"{wr(L):>7.0f}({len(L):>2}){wr(S):>6.0f}({len(S):>2}){sum(r['er'] for r in ts)/len(ts):>8.2f}"
              f"{runover:>8.0f}%")

    # contrast: pooled losers vs winners
    losers = {"2024Q4", "2026Q1"}
    grp = lambda keep: [r for d, q, r in trades if (q in losers) == keep]
    for label, g in (("LOSING quarters", grp(True)), ("OTHER quarters", grp(False))):
        er = sum(r["er"] for r in g) / len(g)
        ro = 100 * sum(r["run_through"] > 1.0 for r in g) / len(g)
        wr = 100 * sum(r["outcome"] == "WIN" for r in g) / len(g)
        print(f"\n{label}: n={len(g)} win={wr:.0f}% meanER={er:.2f} run>1U={ro:.0f}% "
              f"medianRunThrough={sorted(r['run_through'] for r in g)[len(g)//2]:.2f}U")

    # concrete: 3 worst trades in each losing quarter
    for q in sorted(losers):
        ts = sorted([(d, r) for d, qq, r in trades if qq == q], key=lambda x: x[1]["net"])[:3]
        print(f"\n  worst {q} trades:")
        for d, r in ts:
            print(f"    {d} {r['side']:5} {r['outcome']:7} net${r['net']:+7.0f}  "
                  f"ER={r['er']:.2f} ranThrough={r['run_through']:.2f}U")


if __name__ == "__main__":
    main()
