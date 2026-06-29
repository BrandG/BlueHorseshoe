"""Micro-futures cost translation for the opening-range fade (Variant B).

The README's stated rationale for micro index futures is the COST MECHANISM, not a new
price path: MES<->SPY, MNQ<->QQQ, M2K<->IWM track the same indices the edge validated on,
so the intraday path (and therefore the per-trade edge in U) is ~unchanged. What changes is
the cost/tick structure, the absence of PDT, and built-in leverage for a small ($4k) account.

This module answers: does the validated SPY/QQQ/IWM Variant B edge clear *micro-futures*
costs with margin? It needs no futures bars -- the edge is fixed in U; only cost-in-U changes.

Mechanics. A setup's U is STOP_FRAC * R_open in ETF dollars/share (strategy.build_setup).
For the matching micro future, 1U in contract dollars is:
    U_$contract = U_etf_share * (index/ETF ratio) * (futures $ multiplier)
because a $1 ETF move = `ratio` index points, and each index point = `multiplier` dollars.
Gross P&L per contract = pnl_U * U_$contract. Net = that minus a flat round-trip cost.

Run:  ./run.sh python research/opening_range_fade_v1/run.py futures
"""
import os, sys, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
from strategy import simulate
import data as D

# --- micro contract specs (CME) ---
# ratio = index points per $1 of the ETF (SPY=SPX/10, IWM=RUT/10 by ETF construction;
# QQQ~NDX/41 and drifts -- the MNQ cushion is large enough that +/-20% here is immaterial).
MICROS = {
    "SPY": dict(fut="MES", ratio=10.0, mult=5.0, tick_pts=0.25),   # tick = $1.25
    "QQQ": dict(fut="MNQ", ratio=41.0, mult=2.0, tick_pts=0.25),   # tick = $0.50
    "IWM": dict(fut="M2K", ratio=10.0, mult=5.0, tick_pts=0.10),   # tick = $0.50
}

# --- round-trip cost scenarios, $/contract ---
# IBKR micro futures commission is ~$0.25/side + exchange/reg ~$0.37/side ~= $0.62/side.
# Entry and target are LIMIT orders (provide liquidity, ~0 spread); the stop is a market exit
# that pays ~1 tick. Win rate ~42-46%, so ~55-58% of exits cross the spread.
#   cheap        : commission only, no spread (best case, all limit exits)
#   central      : commission + 1 tick on the ~58% of exits that are stops/timeouts
#   conservative : higher commission + 1 tick on BOTH legs (pessimistic)
COMMISSION_RT = {"cheap": 1.24, "central": 1.24, "conservative": 1.50}
SPREAD_FRAC   = {"cheap": 0.0,  "central": 0.58, "conservative": 2.0}  # * tick_$, added to RT


def _trades(setups, bounce_b=C.BOUNCE_B):
    """Per-trade records (only filled trades): (sym, U_etf, outcome, pnl_U)."""
    out = []
    for s in setups:
        outcome, pnl = simulate(s, bounce_b)
        if outcome == "NEVER_FILLED":
            continue
        out.append((s["_sym"], s["U"], outcome, pnl))
    return out


def _fut_econ(sym, trades, scen):
    spec = MICROS[sym]
    tick_dollars = spec["tick_pts"] * spec["mult"]
    rt = COMMISSION_RT[scen] + SPREAD_FRAC[scen] * tick_dollars
    u_to_contract = spec["ratio"] * spec["mult"]   # U_etf_share -> U_$/contract
    gross = net = 0.0
    u_dollars = []
    for (_, u_etf, _o, pnl) in trades:
        u_c = u_etf * u_to_contract
        u_dollars.append(u_c)
        gross += pnl * u_c
        net += pnl * u_c - rt
    n = len(trades)
    return dict(fut=spec["fut"], n=n, rt=rt, tick=tick_dollars,
                gross=gross, net=net,
                exp=net / n if n else 0.0,
                u_med=statistics.median(u_dollars) if u_dollars else 0.0)


def summarize(setups):
    """Structured per-symbol economics, the single source of truth for report() and charts.
    Returns {sym: dict(fut, n, win, u_med, be_rt, scen={name: dict(rt, net, exp, cushion, ok)})}."""
    trades = _trades(setups)
    by_sym = {}
    for t in trades:
        by_sym.setdefault(t[0], []).append(t)
    out = {}
    for sym in ("SPY", "QQQ", "IWM"):
        ts = by_sym.get(sym, [])
        if not ts:
            continue
        spec = MICROS[sym]
        base = _fut_econ(sym, ts, "cheap")
        be_rt = base["gross"] / len(ts) + base["rt"]   # $/contract round-trip that kills the edge
        scen = {}
        for name in ("cheap", "central", "conservative"):
            e = _fut_econ(sym, ts, name)
            scen[name] = dict(rt=e["rt"], net=e["net"], exp=e["exp"],
                              cushion=(be_rt / e["rt"] if e["rt"] else float("inf")),
                              ok=e["net"] > 0)
        out[sym] = dict(fut=spec["fut"], n=len(ts),
                        win=100 * sum(1 for t in ts if t[2] == "WIN") / len(ts),
                        u_med=base["u_med"], be_rt=be_rt, scen=scen)
    return out


def report(period_label, setups, n_days):
    s = summarize(setups)
    total = sum(v["n"] for v in s.values())
    print(f"\n================  {period_label}  ================")
    if n_days:
        print(f"  filled trades: {total}  over ~{n_days} trading days "
              f"({total/n_days:.2f} trades/day across 3 names)\n")
    for sym in ("SPY", "QQQ", "IWM"):
        v = s.get(sym)
        if not v:
            continue
        spec = MICROS[sym]
        print(f"  {sym} -> {v['fut']}  (x{spec['mult']:.0f}/pt, tick ${spec['tick_pts']*spec['mult']:.2f}, "
              f"ratio {spec['ratio']:.0f})   {v['n']} trades, win {v['win']:.1f}%")
        print(f"     median 1U = ${v['u_med']:.2f}/contract   "
              f"break-even round-trip ~= ${v['be_rt']:.2f}/contract")
        for name in ("cheap", "central", "conservative"):
            e = v["scen"][name]
            print(f"       {name:13} rt=${e['rt']:.2f}  net={e['net']:+8.0f}$  "
                  f"exp={e['exp']:+6.2f}$/trade  cushion={e['cushion']:.1f}x  "
                  f"[{'PASS' if e['ok'] else 'FAIL'}]")
    return s


def cmd_futures():
    print("Micro-futures cost translation -- Variant B on SPY/QQQ/IWM.")
    print("Edge is fixed in U; only cost-in-U changes. See futures.py header for mechanics.")
    # P1 = recent (2025-06+), the window the study locked params near.
    # P2 = untouched second period (2024-01 .. 2025-05) -- the honest OOS for cost cushion.
    p1 = D.build_setups(C.SYMBOLS_HOLDOUT, day_min="2025-06")
    p2 = D.build_setups(C.SYMBOLS_HOLDOUT, day_max="2025-06")
    d1 = len({s["_day"] for s in p1});  d2 = len({s["_day"] for s in p2})
    report("P1  2025-06 .. 2026-06  (recent)", p1, d1)
    if p2:
        report("P2  2024-01 .. 2025-05  (untouched OOS)", p2, d2)
    else:
        print("\n  (P2 not pulled yet -- run: pull holdout-p2)")
    print("\nNotes: 1 micro contract per signal. IBKR intraday micro margin ~$50-500/contract,")
    print("so a $4k account day-trading 1-2 micros is unconstrained. No PDT rule on futures.")
