"""Forward paper-trading harness for the opening-range fade (Variant B) on micro futures.

This is the convergence step: a forward run on real futures bars is simultaneously the
real-futures-path test, a true forward OOS, and a limit-fill realism check. Start with MNQ
(the cost winner). Each session it builds the 09:30-09:44 ET opening range, arms the Variant B
limit, simulates the fill through 11:00 ET, converts to $/contract via the contract spec, and
appends one row to forward_paper_log.csv.

Data. Real futures 1-min bars come from the IBKR MCP (get_price_history, FUT, ONE_MIN, RTH).
That feed is dark over the weekend CME halt (Fri 17:00 -> Sun 18:00 ET); pull during an open
session. `ingest_ibkr` converts an MCP price-history response (UTC timestamps) into the same
AV-style cache JSON the loaders already read, so the rest of the study works unchanged.

    # once MNQ bars are cached as MNQU6_YYYY-MM.json:
    ./run.sh python research/opening_range_fade_v1/paper_forward.py MNQ 2026-06-26
    # dry-run today on a cached ETF day as a stand-in (MNQ<->QQQ path is ~identical):
    ./run.sh python research/opening_range_fade_v1/paper_forward.py --demo
"""
import os, sys, csv, json
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
from strategy import build_setup, simulate
import data as D
from futures import MICROS, COMMISSION_RT, SPREAD_FRAC

ET = ZoneInfo("America/New_York")
LOG = os.path.join(C.STUDY_DIR, "forward_paper_log.csv")

# futures spec keyed by root symbol (mirrors futures.MICROS, which is keyed by the ETF analog)
FUT = {v["fut"]: dict(v, etf=k) for k, v in MICROS.items()}   # {"MNQ": {...,"etf":"QQQ"}}


def rt_cost(fut, scen="central"):
    tick_dollars = FUT[fut]["tick_pts"] * FUT[fut]["mult"]
    return COMMISSION_RT[scen] + SPREAD_FRAC[scen] * tick_dollars


def ingest_ibkr(resp, fut, cache_dir=None):
    """Convert an IBKR get_price_history response (UTC ISO timestamps, RTH 1-min) into
    AV-style {SYM}_{YYYY-MM}.json cache files keyed by ET wall-clock. Returns files written."""
    cache_dir = cache_dir or C.PRIMARY_CACHE_DIR
    os.makedirs(cache_dir, exist_ok=True)
    by_month = {}
    for ts, o, h, l, c in zip(resp["time"], resp["open"], resp["high"], resp["low"], resp["close"]):
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(ET)
        key = dt.strftime("%Y-%m-%d %H:%M:%S")
        by_month.setdefault(dt.strftime("%Y-%m"), {})[key] = {
            "1. open": f"{o}", "2. high": f"{h}", "3. low": f"{l}", "4. close": f"{c}"}
    written = []
    for ym, series in by_month.items():
        p = os.path.join(cache_dir, f"{fut}_{ym}.json")
        prior = json.load(open(p)).get("Time Series (1min)", {}) if os.path.exists(p) else {}
        prior.update(series)
        json.dump({"Time Series (1min)": prior}, open(p, "w"))
        written.append(p)
    return written


def _record(label, day, bars, fut, scen="central"):
    """Build + simulate one session; return a log row (or None if no qualifying setup)."""
    s = build_setup(bars)
    if not s:
        return None
    spec = FUT[fut]
    outcome, pnl_u = simulate(s, bounce_b=C.BOUNCE_B)
    u_dollars = s["U"] * spec["ratio"] * spec["mult"]
    if outcome == "NEVER_FILLED":
        return dict(label=label, day=day, fut=fut, side=s["side"], setup="armed",
                    outcome="NEVER_FILLED", u_dollars=round(u_dollars, 2),
                    gross=0.0, cost=0.0, net=0.0)
    cost = rt_cost(fut, scen)
    gross = pnl_u * u_dollars
    return dict(label=label, day=day, fut=fut, side=s["side"], setup="armed",
                outcome=outcome, u_dollars=round(u_dollars, 2),
                gross=round(gross, 2), cost=round(cost, 2), net=round(gross - cost, 2))


def append_log(row):
    new = not os.path.exists(LOG)
    with open(LOG, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if new:
            w.writeheader()
        w.writerow(row)


def run_day(fut, day, scen="central", log=True):
    bars = D.load_intraday(fut).get(day)
    if not bars:
        print(f"no cached bars for {fut} {day} (pull/ingest first)")
        return None
    row = _record(f"{fut}-real", day, bars, fut, scen)
    if not row:
        print(f"{fut} {day}: no qualifying setup (doji / range below ATR floor)")
        return None
    if log:
        append_log(row)
    print(f"{fut} {day}: {row['side']} -> {row['outcome']}  net ${row['net']:+.2f}/contract"
          f"  (1U=${row['u_dollars']}, cost=${row['cost']})")
    return row


def demo():
    """Today, CME is shut -> no MNQ bars. Demonstrate the engine on the most recent cached QQQ
    session using the MNQ spec (QQQ<->MNQ path is ~identical). NOT logged (label demo)."""
    days = sorted(D.load_intraday("QQQ"))
    if not days:
        print("no QQQ cache; run: run.py pull")
        return
    day = days[-1]
    bars = D.load_intraday("QQQ")[day]
    row = _record("MNQ-demo(QQQ-path)", day, bars, "MNQ")
    print("DEMO (QQQ path priced as MNQ, not logged):")
    print(f"  {day}: {row['side']} -> {row['outcome']}  net ${row['net']:+.2f}/contract"
          f"  (1U=${row['u_dollars']}, cost=${row['cost']})")
    print(f"\nWhen CME is open: ingest MNQ bars via ingest_ibkr(mcp_response, 'MNQ'),")
    print(f"then: run_day('MNQ', '<day>'). Forward trades log to {LOG}")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--demo":
        demo()
    elif len(sys.argv) >= 3:
        run_day(sys.argv[1], sys.argv[2])
    else:
        print(__doc__)
