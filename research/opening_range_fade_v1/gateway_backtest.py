"""Roll-stitched REAL micro-futures backtest for the opening-range fade (Variant B).

Unlike `futures.py` (which re-costs the ETF price path), this runs the strategy on REAL futures
1-min bars, stitched across quarterly contract rolls so each trading date uses the contract that
was actually the liquid front month then. Data comes from the project's CME-entitled paper IB
Gateway (the claude.ai MCP is not entitled). Gateway timestamps are Central -> converted to ET.

Roll rule: date D uses the nearest quarterly contract whose expiry is > D + ROLL_BUFFER_DAYS
(~the standard ~8-day-before-3rd-Friday liquidity roll). Each contract's active window is
[prev_roll, this_roll); ATR_14 is computed within each contract (no roll-gap spikes).

    ./run.sh python research/opening_range_fade_v1/gateway_backtest.py MNQ          # pull (cached) + report
    ./run.sh python research/opening_range_fade_v1/gateway_backtest.py MNQ --no-pull  # report from cache only

P&L is $/contract, net of the same cost scenarios as futures.py.
"""
import os, sys, time, json
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
import data as D
from strategy import simulate
from futures import MICROS, COMMISSION_RT, SPREAD_FRAC

ET = ZoneInfo("America/New_York")
HOST, PORT, CLIENT_ID = "127.0.0.1", 4004, 79
ROLL_BUFFER_DAYS = 8
EARLIEST = "2024-07-01"            # how far back to stitch (bounded by HMDS 1-min retention)
ROOT_MULT = {"MNQ": 2.0, "MES": 5.0, "M2K": 5.0}
ROOT_EXCH = {"MNQ": "CME", "MES": "CME", "M2K": "CME"}


# ---------------- contract calendar ----------------
def contract_windows(ib, root):
    """[(contract, active_start 'YYYY-MM-DD', active_end exclusive 'YYYY-MM-DD')] front-month windows."""
    from ib_async import Future
    det = ib.reqContractDetails(Future(root, exchange=ROOT_EXCH[root], currency="USD",
                                       includeExpired=True))
    cons = sorted((d.contract for d in det), key=lambda c: c.lastTradeDateOrContractMonth)
    today = datetime.now(ET).date()
    rolls = []  # (contract, expiry_date, roll_date)
    for c in cons:
        exp = datetime.strptime(c.lastTradeDateOrContractMonth[:8], "%Y%m%d").date()
        rolls.append((c, exp, exp - timedelta(days=ROLL_BUFFER_DAYS)))
    floor = datetime.strptime(EARLIEST, "%Y-%m-%d").date()
    out = []
    for i, (c, exp, roll) in enumerate(rolls):
        start = rolls[i - 1][2] if i > 0 else roll - timedelta(days=100)
        end = roll
        if end <= floor:                       # window entirely before our floor
            continue
        if start < floor:
            start = floor
        if start >= today:                     # not yet active
            continue
        if end > today:                        # current front month -> open-ended to today
            end = today + timedelta(days=1)
        out.append((c, start.isoformat(), end.isoformat()))
    return out


# ---------------- pull + cache (per localSymbol, AV-style, ET) ----------------
def _cache_1m(sym, bars):
    by_month = defaultdict(dict)
    for b in bars:
        dt = b.date.astimezone(ET)
        by_month[dt.strftime("%Y-%m")][dt.strftime("%Y-%m-%d %H:%M:%S")] = {
            "1. open": f"{b.open}", "2. high": f"{b.high}", "3. low": f"{b.low}", "4. close": f"{b.close}"}
    os.makedirs(C.PRIMARY_CACHE_DIR, exist_ok=True)
    for ym, series in by_month.items():
        p = os.path.join(C.PRIMARY_CACHE_DIR, f"{sym}_{ym}.json")
        prior = json.load(open(p)).get("Time Series (1min)", {}) if os.path.exists(p) else {}
        prior.update(series)
        json.dump({"Time Series (1min)": prior}, open(p, "w"))


def _cache_daily(sym, bars):
    series = {b.date.strftime("%Y-%m-%d"): {"2. high": f"{b.high}", "3. low": f"{b.low}",
                                            "4. close": f"{b.close}"} for b in bars}
    json.dump({"Time Series (Daily)": series},
              open(os.path.join(C.PRIMARY_CACHE_DIR, f"{sym}_DAILY.json"), "w"))


def _is_cached(sym):
    import glob
    return (bool(glob.glob(os.path.join(C.PRIMARY_CACHE_DIR, f"{sym}_2*.json")))
            and os.path.exists(os.path.join(C.PRIMARY_CACHE_DIR, f"{sym}_DAILY.json")))


def pull_contract(ib, contract, start, end):
    sym = contract.localSymbol
    if _is_cached(sym):
        print(f"  {sym}: cached, skip  [{start}..{end})", flush=True)
        return
    end_dt = min(datetime.strptime(end, "%Y-%m-%d"), datetime.now()) + timedelta(days=1)
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    seen, all_1m, cur = set(), [], end_dt
    while cur > start_dt:
        # Some contracts time out on a big "2 M" pull; retry, then fall back to smaller chunks.
        bars = None
        for dur in ("2 M", "1 M", "2 W", "2 W", "1 W"):
            bars = ib.reqHistoricalData(contract, endDateTime=cur.strftime("%Y%m%d-21:00:00"),
                                        durationStr=dur, barSizeSetting="1 min",
                                        whatToShow="TRADES", useRTH=True, formatDate=2,
                                        timeout=180)
            time.sleep(3.0)                               # HMDS pacing (60 req / 10 min)
            if bars:
                break
        if not bars:
            print(f"    {sym}: no data near {cur.date()} after retries — stopping", flush=True)
            break
        for b in bars:
            k = b.date.isoformat()
            if k not in seen:
                seen.add(k); all_1m.append(b)
        cur = bars[0].date.astimezone(ET).replace(tzinfo=None)
    _cache_1m(sym, all_1m)
    daily = ib.reqHistoricalData(contract, endDateTime=end_dt.strftime("%Y%m%d-21:00:00"),
                                 durationStr="9 M", barSizeSetting="1 day",
                                 whatToShow="TRADES", useRTH=True, formatDate=1)
    time.sleep(3.0)
    _cache_daily(sym, daily)
    print(f"  {sym}: {len(all_1m)} 1-min bars, {len(daily)} daily  [{start}..{end})", flush=True)


def ensure_data(root):
    from ib_async import IB
    ib = IB()
    ib.connect(HOST, PORT, clientId=CLIENT_ID, timeout=10, readonly=True)
    wins = contract_windows(ib, root)
    print(f"{root}: {len(wins)} front-month windows {wins[0][1]}..{wins[-1][2]}", flush=True)
    for c, s, e in wins:
        pull_contract(ib, c, s, e)
    ib.disconnect()
    return wins


# ---------------- backtest ----------------
def _econ(trades, root, scen):
    mult = ROOT_MULT[root]
    tick = MICROS[{"MNQ": "QQQ", "MES": "SPY", "M2K": "IWM"}[root]]["tick_pts"] * mult
    rt = COMMISSION_RT[scen] + SPREAD_FRAC[scen] * tick
    net = sum(p * u * mult - rt for (p, u, _o) in trades)
    return rt, net


def run(root, pull=True):
    if pull:
        wins = ensure_data(root)
    else:
        # reconstruct windows offline from cached daily files + a fresh contract list is not
        # available without a connection; require a prior pull. Re-pull is cheap-ish, so default on.
        from ib_async import IB
        ib = IB(); ib.connect(HOST, PORT, clientId=CLIENT_ID, timeout=10, readonly=True)
        wins = contract_windows(ib, root); ib.disconnect()
    mult = ROOT_MULT[root]
    trades = []   # (pnl_U, U_points, outcome) with date/quarter tags alongside
    tagged = []
    for c, s, e in wins:
        sym = c.localSymbol
        for st in D.build_setups([sym], day_min=s, day_max=e):
            o, pnl = simulate(st, C.BOUNCE_B)
            if o == "NEVER_FILLED":
                continue
            trades.append((pnl, st["U"], o))
            tagged.append((st["_day"], st["_q"], pnl, st["U"], o, sym))
    if not trades:
        print("no trades — pull may have failed"); return
    days = sorted({t[0] for t in tagged})
    W = sum(1 for t in trades if t[2] == "WIN"); L = sum(1 for t in trades if t[2] == "LOSS")
    print(f"\n==== REAL {root} roll-stitched, Variant B  ({len(days)} trade-days "
          f"{days[0]}..{days[-1]}, {len(wins)} contracts) ====")
    print(f"  fills={len(trades)}  W/L/TO={W}/{L}/{len(trades)-W-L}  win={100*W/(W+L) if W+L else 0:.1f}%")
    med = sorted(t[1]*mult for t in trades)[len(trades)//2]
    for scen in ("cheap", "central", "conservative"):
        rt, net = _econ(trades, root, scen)
        print(f"  {scen:13} rt=${rt:.2f}  net=${net:+8.0f}/contract  exp=${net/len(trades):+6.2f}/trade")
    print(f"  median 1U=${med:.2f}/contract")

    print("\n  --- per-quarter (central cost) ---")
    byq = defaultdict(list)
    for d, q, pnl, u, o, sym in tagged:
        byq[q].append((pnl, u, o))
    for q in sorted(byq):
        _, net = _econ(byq[q], root, "central")
        w = sum(1 for t in byq[q] if t[2] == "WIN"); n = len(byq[q])
        print(f"    {q}: {n:3} fills  win {100*w/n:4.0f}%  net ${net:+7.0f}/contract")

    # OOS split: first 60% of trade-days = train-era, last 40% = holdout (chronological)
    split = days[int(len(days)*0.6)]
    early = [(p, u, o) for (d, q, p, u, o, s) in tagged if d < split]
    late = [(p, u, o) for (d, q, p, u, o, s) in tagged if d >= split]
    print(f"\n  --- chronological split at {split} (central cost) ---")
    for label, sub in (("first 60%", early), ("last 40% (holdout)", late)):
        _, net = _econ(sub, root, "central")
        w = sum(1 for t in sub if t[2] == "WIN"); n = len(sub)
        print(f"    {label:20}: {n:3} fills  win {100*w/n if n else 0:4.0f}%  net ${net:+7.0f}/contract")


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "MNQ"
    run(root, pull="--no-pull" not in sys.argv)
