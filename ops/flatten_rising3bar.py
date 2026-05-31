#!/usr/bin/env python3
"""One-time retirement flatten: close the 7 rising_3bar-tagged OANDA demo trades.

Safe to run repeatedly — it re-derives the target set from LIVE state each time and
only closes trades whose clientExtensions tag starts with 'rising3bar'. If the forex
market is halted (weekend), each close is auto-cancelled with MARKET_HALTED and the
script reports 'halted, retry after market open' without error. Writes an audit row
ONLY for trades that actually filled.

Run:  cd /root/BlueHorseshoe && ./run.sh python /tmp/flatten_rising3bar.py
"""
import csv
import sys
from datetime import UTC, datetime
from pathlib import Path

import requests

REPO = Path("/root/BlueHorseshoe")
env = {}
for line in (REPO / ".env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
tok = env["OANDA_DEMO_TOKEN"]
acct = env["OANDA_DEMO_ACCOUNT_ID"]
base = "https://api-fxpractice.oanda.com"
h = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def tag(t):
    ce = t.get("clientExtensions") or {}
    return str(ce.get("tag") or ce.get("id") or "")


def open_trades():
    r = requests.get(f"{base}/v3/accounts/{acct}/trades",
                     params={"state": "OPEN", "count": "500"}, headers=h, timeout=30)
    return r.json().get("trades", [])


def main():
    targets = [t for t in open_trades() if tag(t).startswith("rising3bar")]
    if not targets:
        print("No rising3bar-tagged trades open — nothing to do (already flattened).")
        return 0
    if not all(int(t["currentUnits"]) > 0 for t in targets):
        print("GUARD: a rising3bar trade is not long — abort, inspect manually.")
        return 2

    print(f"Closing {len(targets)} rising3bar-tagged trade(s) by trade ID:\n")
    realized = 0.0
    halted = 0
    audit = []
    for t in targets:
        tid, inst = t["id"], t["instrument"]
        r = requests.put(f"{base}/v3/accounts/{acct}/trades/{tid}/close",
                         headers=h, json={"units": "ALL"}, timeout=30)
        j = r.json()
        fill = j.get("orderFillTransaction")
        cancel = j.get("orderCancelTransaction")
        if fill:
            pl = float(fill.get("pl", 0))
            realized += pl
            print(f"  OK     {inst:8} trade {tid:>4}  closed@{fill.get('price','?')}  realizedPL={pl:+8.2f}")
            audit.append({"ts_utc": datetime.now(UTC).isoformat(), "event": "retire_flatten",
                          "instrument": inst, "units": t["currentUnits"], "trade_id": tid,
                          "realized_pl": f"{pl:.4f}", "note": "rising_3bar retirement"})
        elif cancel:
            reason = cancel.get("reason", "?")
            halted += (reason == "MARKET_HALTED")
            print(f"  SKIP   {inst:8} trade {tid:>4}  not closed: {reason}")
        else:
            print(f"  ERR    {inst:8} trade {tid:>4}  HTTP {r.status_code}: {str(j)[:120]}")

    if audit:
        jp = REPO / "src/logs/bh_ftmo_retire_flatten.csv"
        new = not jp.exists()
        with jp.open("a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["ts_utc", "event", "instrument", "units",
                                              "trade_id", "realized_pl", "note"])
            if new:
                w.writeheader()
            w.writerows(audit)
        print(f"\nTotal realized P&L: {realized:+.2f}   audit -> {jp}")

    left = [t for t in open_trades() if tag(t).startswith("rising3bar")]
    print(f"\nrising3bar-tagged still open: {len(left)}")
    if halted and left:
        print("Market is HALTED (weekend). Re-run after forex reopens (~Sun 21:00 UTC).")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
