"""Pull real micro-futures 1-min + daily bars from the project's IB Gateway (CME-entitled,
unlike the claude.ai IBKR MCP). Writes them into the study's cache in the same AV-style JSON
the loaders already read, converting the gateway's local (Central) timestamps to ET wall-clock
so build_setup's 09:30-ET window logic works unchanged.

    ./run.sh python research/opening_range_fade_v1/gateway_pull.py MNQ 30   # ~30 calendar days

Read-only, dedicated client_id. Front-month contract is auto-selected; for a multi-month history
you'd stitch across quarterly rolls (front contract per date) -- this first pass pulls the current
front month only, enough for a real-data taste + the start of a forward log.
"""
import os, sys, json
from collections import defaultdict
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
import ib_async
from ib_async import IB, Future

ET = ZoneInfo("America/New_York")
HOST, PORT, CLIENT_ID = "127.0.0.1", 4004, 77

# root -> CME exchange spec for qualification
ROOTS = {"MNQ": ("MNQ", "CME"), "MES": ("MES", "CME"), "M2K": ("M2K", "CME")}


def _front_contract(ib, root):
    sym, exch = ROOTS[root]
    details = ib.reqContractDetails(Future(sym, exchange=exch, currency="USD"))
    cons = sorted((d.contract for d in details), key=lambda c: c.lastTradeDateOrContractMonth)
    return cons[0]


def _write_cache(root, bars_1m):
    """bars_1m: list of ib_async BarData (1-min). Write per-month AV-style JSON keyed by ET."""
    by_month = defaultdict(dict)
    for b in bars_1m:
        dt = b.date.astimezone(ET) if b.date.tzinfo else b.date.replace(tzinfo=ET)
        by_month[dt.strftime("%Y-%m")][dt.strftime("%Y-%m-%d %H:%M:%S")] = {
            "1. open": f"{b.open}", "2. high": f"{b.high}",
            "3. low": f"{b.low}", "4. close": f"{b.close}"}
    os.makedirs(C.PRIMARY_CACHE_DIR, exist_ok=True)
    for ym, series in by_month.items():
        p = os.path.join(C.PRIMARY_CACHE_DIR, f"{root}_{ym}.json")
        prior = json.load(open(p)).get("Time Series (1min)", {}) if os.path.exists(p) else {}
        prior.update(series)
        json.dump({"Time Series (1min)": prior}, open(p, "w"))
    return sorted(by_month)


def _write_daily(root, bars_d):
    if not bars_d:
        return 0          # never clobber a good ATR cache with an empty/failed fetch
    series = {}
    for b in bars_d:
        d = b.date.strftime("%Y-%m-%d") if hasattr(b.date, "strftime") else str(b.date)
        series[d] = {"2. high": f"{b.high}", "3. low": f"{b.low}", "4. close": f"{b.close}"}
    p = os.path.join(C.PRIMARY_CACHE_DIR, f"{root}_DAILY.json")
    prior = json.load(open(p)).get("Time Series (Daily)", {}) if os.path.exists(p) else {}
    prior.update(series)  # merge, so a short refresh never drops older ATR-warmup history
    json.dump({"Time Series (Daily)": prior}, open(p, "w"))
    return len(prior)


def pull(root, days):
    ib = IB()
    ib.connect(HOST, PORT, clientId=CLIENT_ID, timeout=8, readonly=True)
    print(f"connected={ib.isConnected()} sv={ib.client.serverVersion()}")
    con = _front_contract(ib, root)
    print(f"front: {con.localSymbol} expiry={con.lastTradeDateOrContractMonth}")

    # 1-min RTH, chunked backward in 5-day windows (HMDS caps 1-min request duration).
    all_1m, seen, end = [], set(), ""
    for _ in range((days // 5) + 1):
        bars = ib.reqHistoricalData(con, endDateTime=end, durationStr="5 D",
                                    barSizeSetting="1 min", whatToShow="TRADES",
                                    useRTH=True, formatDate=2)  # formatDate=2 -> tz-aware UTC
        if not bars:
            break
        for b in bars:
            k = b.date.isoformat()
            if k not in seen:
                seen.add(k); all_1m.append(b)
        end = bars[0].date.strftime("%Y%m%d-%H:%M:%S")
    months = _write_cache(root, all_1m)
    print(f"1-min: {len(all_1m)} bars across months {months}")

    daily = ib.reqHistoricalData(con, endDateTime="", durationStr="3 M",
                                 barSizeSetting="1 day", whatToShow="TRADES",
                                 useRTH=True, formatDate=1)
    nd = _write_daily(root, daily)
    print(f"daily: {nd} bars -> {root}_DAILY.json (for ATR_14 filter)")
    ib.disconnect()
    return {"contract": con.localSymbol, "n_1m": len(all_1m), "n_daily": nd}


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "MNQ"
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    print(f"ib_async {ib_async.__version__}  pulling {root} ~{days}d")
    pull(root, days)
