"""BH FTMO operator tool — one-screen account + recent-activity status.

Run any time. Prints:
  1. OANDA account state (NAV, balance, margin util, position count, direction split)
  2. Currently-open positions ordered by unrealized P&L (worst first)
  3. Recent journal activity from each paper trader, broken down by event
     (order_placed, skip_already_open, skip_margin_util, skip_direction_imbalance, …)

Use --hours to widen/narrow the journal lookback window (default 48h).
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Optional

from bh_ftmo.trading.oanda_trader import (
    OandaTrader,
    OandaTraderConfig,
    OandaTraderError,
)
from bh_ftmo.trading.safety import (
    MAX_MARGIN_UTILIZATION,
    MAX_NET_DIRECTION_IMBALANCE,
    count_open_directions,
    margin_utilization,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
LOGS_DIR = REPO_ROOT / "src" / "logs"

JOURNALS = {
    "bh_ftmo_trader": LOGS_DIR / "bh_ftmo_trader_journal.csv",
    "rising_3bar": LOGS_DIR / "bh_ftmo_paper_journal.csv",
    "v2_paper":    LOGS_DIR / "bh_ftmo_v2_paper_journal.csv",
    "flatten":     LOGS_DIR / "bh_ftmo_flatten_journal.csv",
}


def _print_account(trader: OandaTrader) -> None:
    summary = trader.get_account_summary()
    positions = trader.get_open_positions()
    nav = float(summary.get("NAV", 0.0))
    bal = float(summary.get("balance", 0.0))
    mu = float(summary.get("marginUsed", 0.0))
    util = margin_utilization(summary)
    n_long, n_short = count_open_directions(positions)

    margin_flag = "  ⚠ OVER CAP" if util > MAX_MARGIN_UTILIZATION else ""
    imbal = abs(n_long - n_short)
    dir_flag = "  ⚠ OVER CAP" if imbal > MAX_NET_DIRECTION_IMBALANCE else ""

    print("=== ACCOUNT ===")
    print(f"NAV             {nav:>12,.2f}")
    print(f"Balance         {bal:>12,.2f}")
    print(f"MarginUsed      {mu:>12,.2f}")
    print(f"MarginUtil      {util:>12.1%}   (gate cap {MAX_MARGIN_UTILIZATION:.0%}){margin_flag}")
    print(f"Positions       {len(positions):>12d}   (long={n_long} short={n_short} imbalance={imbal}, gate cap {MAX_NET_DIRECTION_IMBALANCE}){dir_flag}")
    print()

    if positions:
        rows = []
        for p in positions:
            long_u = int(p["long"]["units"])
            short_u = int(p["short"]["units"])
            side = "L" if long_u != 0 else ("S" if short_u != 0 else "-")
            units = long_u if long_u != 0 else short_u
            margin = float(p.get("marginUsed", 0))
            upl = float(p["unrealizedPL"])
            rows.append((p["instrument"], side, units, margin, upl))
        rows.sort(key=lambda r: r[4])  # worst PL first
        print("=== POSITIONS (worst → best unrealized P&L) ===")
        print(f"{'instrument':10s} {'sd':2s} {'units':>10s}  {'margin_$':>10s}  {'unrealPL_$':>11s}")
        for inst, side, u, m, upl in rows:
            print(f"{inst:10s} {side:2s} {u:>10d}  {m:>10,.2f}  {upl:>+11,.2f}")
        total_upl = sum(r[4] for r in rows)
        print(f"{'TOTAL':10s}                              {sum(r[3] for r in rows):>10,.2f}  {total_upl:>+11,.2f}")
        print()


def _summarize_journal(label: str, path: Path, since: datetime) -> None:
    if not path.exists():
        print(f"=== {label.upper()} JOURNAL: (no file at {path.name}) ===")
        print()
        return
    counts: Counter = Counter()
    recent_orders: list[tuple[str, str, str]] = []
    n_rows = 0
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts_raw = row.get("ts_utc", "")
            try:
                ts = datetime.fromisoformat(ts_raw)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
            except ValueError:
                continue
            if ts < since:
                continue
            n_rows += 1
            evt = row.get("event", "")
            counts[evt] += 1
            if evt == "order_placed":
                pair = row.get("pair") or row.get("instrument", "")
                strat = row.get("strategy") or "rising_3bar"
                recent_orders.append((ts.isoformat(timespec="minutes"), strat, pair))

    print(f"=== {label.upper()} JOURNAL (last {n_rows} rows since {since.isoformat(timespec='minutes')}) ===")
    if not counts:
        print("  (no activity)")
    else:
        for evt, n in counts.most_common():
            print(f"  {evt:30s} {n:>4d}")
    if recent_orders:
        print("  recent orders:")
        for ts, strat, pair in recent_orders[-5:]:
            print(f"    {ts}  {strat:12s}  {pair}")
    print()


def run(*, hours: float) -> int:
    try:
        cfg = OandaTraderConfig.from_env()
    except OandaTraderError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    since = datetime.now(UTC) - timedelta(hours=hours)
    print(f"BH FTMO status @ {datetime.now(UTC).isoformat(timespec='seconds')}  (lookback {hours:g}h)")
    print()

    with OandaTrader(cfg) as trader:
        try:
            _print_account(trader)
        except OandaTraderError as exc:
            print(f"ERROR fetching account: {exc}", file=sys.stderr)
            return 1

    for label, path in JOURNALS.items():
        _summarize_journal(label, path, since)
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="BH FTMO account + journal status")
    parser.add_argument("--hours", type=float, default=48.0,
                        help="journal lookback window in hours (default 48)")
    args = parser.parse_args(argv)
    return run(hours=args.hours)


if __name__ == "__main__":
    raise SystemExit(main())
