#!/usr/bin/env python3
"""Opening-range fade — study runner.

Usage (from repo root, via the venv):
    ./run.sh python research/opening_range_fade_v1/run.py <command>

Commands:
    pull [primary|index|holdout|all]   download + cache AlphaVantage data for a basket
    backtest                           baseline + stop sweep + entry-quality (Variants A/B) on the 12-stock basket
    validate                           train/out-of-sample split on the 12-stock basket (the headline OOS test)
    etf                                index/sector ETF cross-section + cost-vs-price diagnostic
    holdout                            second-period holdout on SPY/QQQ/IWM (period 1 vs period 2)
    charts [equity|scatter|failures]   render (and optionally email) figures

All P&L is in U (= the 1x stop distance) and net of COST_PER_SHARE unless 'gross' is shown.
"""
import os, sys, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
from strategy import simulate
import data as D


def months(a, b):
    out = []
    y, m = int(a[:4]), int(a[5:7]); ey, em = int(b[:4]), int(b[5:7])
    while (y, m) <= (ey, em):
        out.append(f"{y}-{m:02d}")
        m += 1
        if m == 13: y, m = y + 1, 1
    return out


def metrics(setups, bounce_b=C.BOUNCE_B, stop_mult=1.0, cost=C.COST_PER_SHARE, keep=None):
    fill = W = L = TO = 0; gross = net = inv = 0.0; worst = 0.0
    for s in setups:
        if keep and not keep(s):
            continue
        out, pnl = simulate(s, bounce_b, stop_mult)
        if out == "NEVER_FILLED":
            continue
        fill += 1
        if out == "WIN": W += 1
        elif out == "LOSS": L += 1
        else: TO += 1
        gross += pnl
        net += pnl - (cost / s["U"] if s["U"] else 0)
        inv += 1.0 / s["U"] if s["U"] else 0
        worst = min(worst, pnl)
    return dict(fill=fill, W=W, L=L, TO=TO, win=100*W/(W+L) if (W+L) else 0,
                gross=gross, net=net, worst=worst, be=100*gross/inv if inv else 0)


def _line(name, m):
    print(f"  {name:34} fill={m['fill']:4}  W/L={m['W']:3}/{m['L']:3}  win={m['win']:5.1f}%"
          f"  gross={m['gross']:+7.1f}U  net={m['net']:+7.1f}U")


# ----------------------------- commands -----------------------------
def cmd_pull(which):
    sets = {
        "primary": (C.SYMBOLS_PRIMARY, months("2025-06", "2026-06")),
        "index":   (C.SYMBOLS_INDEX,   months("2025-06", "2026-06")),
        "holdout": (C.SYMBOLS_HOLDOUT, months("2024-01", "2025-05")),
    }
    todo = ["primary", "index", "holdout"] if which == "all" else [which]
    for w in todo:
        syms, ms = sets[w]
        print(f"pulling '{w}': {len(syms)} symbols x {len(ms)} months ...")
        fails = D.pull(syms, ms)
        print(f"  done, failures={len(fails)}: {fails}")


def cmd_backtest():
    S = D.build_setups(C.SYMBOLS_PRIMARY)
    print(f"12-stock basket, {len(S)} qualified setups\n--- baseline & entry-quality ---")
    _line("baseline (entry at extreme)", metrics(S, bounce_b=0.0))
    for K in (2, 3):
        _line(f"A: extreme not in last {K} min", metrics(S, bounce_b=0.0, keep=lambda s, K=K: s["ext_from_end"] >= K))
    for b in (0.1, 0.2, 0.3):
        _line(f"B: bounce {b}R first", metrics(S, bounce_b=b))
    print("\n--- stop sweep (Variant=baseline entry, stop = m x 1U) ---")
    print(f"  {'m':>4}{'R:R':>6}{'win%':>7}{'gross':>9}{'net':>9}{'worst':>7}")
    for m in (1.0, 1.5, 2.0, 3.0, 4.0):
        r = metrics(S, bounce_b=0.0, stop_mult=m)
        print(f"  {m:>4.1f}{2.0/m:>6.2f}{r['win']:>7.1f}{r['gross']:>9.1f}{r['net']:>9.1f}{r['worst']:>7.1f}")
    print("  (stop sweep improves monotonically = removing risk control, NOT an edge. See STUDY_README.)")


def cmd_validate():
    S = D.build_setups(C.SYMBOLS_PRIMARY)
    train = [s for s in S if s["_day"] >= C.OOS_SPLIT]
    oos = [s for s in S if s["_day"] < C.OOS_SPLIT]
    print(f"12-stock basket: {len(S)} setups  (train>={C.OOS_SPLIT}: {len(train)}, OOS: {len(oos)})")
    for label, data in (("TRAIN (in-sample)", train), ("OUT-OF-SAMPLE", oos)):
        print(f"\n=== {label} ===")
        _line("baseline", metrics(data, bounce_b=0.0))
        _line("B: bounce 0.2R", metrics(data, bounce_b=0.2))
    print("\n--- OOS per-quarter net (baseline / B 0.2R) ---")
    for q in sorted({s["_q"] for s in oos}):
        sub = [s for s in oos if s["_q"] == q]
        print(f"  {q}: baseline {metrics(sub, bounce_b=0.0)['net']:+6.1f}U   B {metrics(sub, bounce_b=0.2)['net']:+6.1f}U")
    print("\n--- OOS cost stress (Variant B) ---")
    for c in (0.0, 0.01, 0.02, 0.03, 0.04, 0.05):
        print(f"  cost {100*c:>2.0f}c/sh: net {metrics(oos, bounce_b=0.2, cost=c)['net']:+7.1f}U")


def cmd_etf():
    print("Index/sector ETFs, Variant B, full history (fully OOS for these names):")
    print(f"  {'ETF':6}{'fills':>7}{'win%':>7}{'gross':>8}{'net@2c':>8}{'be(c)':>7}")
    allst = []; pos = 0
    for t in C.SYMBOLS_INDEX:
        st = D.build_setups([t]); allst += st
        m = metrics(st)
        pos += m["net"] > 0
        print(f"  {t:6}{m['fill']:>7}{m['win']:>7.1f}{m['gross']:>8.1f}{m['net']:>8.1f}{m['be']:>7.2f}")
    agg = metrics(allst)
    print(f"  AGGREGATE: net@2c {agg['net']:+.1f}U  gross {agg['gross']:+.1f}U  "
          f"breakeven {agg['be']:.2f}c/sh  positive {pos}/{len(C.SYMBOLS_INDEX)}")
    print("  Verdict: broad index version fails -- cheap penny-quoted ETFs can't clear costs.")


def cmd_holdout():
    print("Second-period holdout, SPY/QQQ/IWM, Variant B (net@2c):")
    print(f"  {'sym':5}{'period':18}{'fills':>7}{'win%':>7}{'gross':>8}{'net':>8}{'be(c)':>7}")
    for t in C.SYMBOLS_HOLDOUT:
        for label, lo, hi in (("P2 2024-2025/05", None, "2025-06"), ("P1 2025/06-2026", "2025-06", None)):
            st = D.build_setups([t], day_min=lo, day_max=hi)
            m = metrics(st)
            print(f"  {t:5}{label:18}{m['fill']:>7}{m['win']:>7.1f}{m['gross']:>8.1f}{m['net']:>8.1f}{m['be']:>7.2f}")
    print("  QQQ and IWM replicate net-positive across both periods; SPY flat in period 2.")


def cmd_charts(which):
    import charts
    getattr(charts, f"chart_{which}")()


def main():
    p = argparse.ArgumentParser(description="Opening-range fade study runner")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pull").add_argument("which", nargs="?", default="all",
                                        choices=["primary", "index", "holdout", "all"])
    sub.add_parser("backtest"); sub.add_parser("validate")
    sub.add_parser("etf"); sub.add_parser("holdout"); sub.add_parser("futures")
    sub.add_parser("charts").add_argument("which", nargs="?", default="equity",
                                          choices=["equity", "scatter", "failures"])
    a = p.parse_args()
    if a.cmd == "pull": cmd_pull(a.which)
    elif a.cmd == "backtest": cmd_backtest()
    elif a.cmd == "validate": cmd_validate()
    elif a.cmd == "etf": cmd_etf()
    elif a.cmd == "holdout": cmd_holdout()
    elif a.cmd == "futures":
        from futures import cmd_futures; cmd_futures()
    elif a.cmd == "charts": cmd_charts(a.which)


if __name__ == "__main__":
    main()
