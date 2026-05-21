"""BH Swing — human-readable review of dry-run advancement decisions.

Reads ``would_advance_stop`` rows from the journal for a given date and joins
each one with current broker state, Mongo ``trade_orders`` metadata, and a
Tiingo quote so the proposed stop move can be evaluated in context.

Usage:
  ./run.sh python src/bh_swing_review.py                # default: today UTC
  ./run.sh python src/bh_swing_review.py --date 2026-05-20
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone

from bh_live_status import _fetch_tiingo_last_prices  # noqa: PLC0415
from bh_swing import journal
from bh_swing.analysis import position_state
from bluehorseshoe.core.config import get_settings
from bluehorseshoe.core.container import create_app_container
from bluehorseshoe.data.ibkr_client import IBKRClient, IBKRConfig

logger = logging.getLogger("bh_swing.review")

DEFAULT_CLIENT_ID = int(os.environ.get("BH_SWING_CLIENT_ID", "7"))

GREEN = "\033[32m"
RED = "\033[31m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _latest_would_advance_rows(date_str: str) -> list[dict]:
    """Return one row per (symbol, order_id) — the latest event from that day."""
    rows = journal.read_recent(limit=10_000)
    by_key: dict[tuple[str, str], dict] = {}
    for r in rows:
        if r.get("event") != "would_advance_stop":
            continue
        ts = str(r.get("ts_utc", ""))
        if not ts.startswith(date_str):
            continue
        key = (str(r.get("symbol", "")), str(r.get("order_id", "")))
        prev = by_key.get(key)
        if prev is None or ts > str(prev.get("ts_utc", "")):
            by_key[key] = r
    return sorted(by_key.values(), key=lambda r: str(r.get("symbol", "")))


def _color(text: str, ok: bool, use_color: bool) -> str:
    if not use_color:
        return text
    return f"{GREEN if ok else RED}{text}{RESET}"


def _print_review_block(
    row: dict,
    managed_by_symbol: dict[str, position_state.ManagedPosition],
    quotes: dict,
    use_color: bool,
) -> None:
    sym = str(row.get("symbol", ""))
    order_id = str(row.get("order_id", ""))
    journaled_old_stop = float(row.get("stop_price", 0) or 0)
    journaled_new_stop = float(row.get("price", 0) or 0)
    journaled_target = float(row.get("target_price", 0) or 0)
    ts = str(row.get("ts_utc", ""))[:19].replace("T", " ")

    print(f"\n{BOLD}{sym}{RESET}  T1→breakeven  order_id={order_id}  "
          f"{DIM}last seen {ts} UTC{RESET}")

    pos = managed_by_symbol.get(sym)
    quote = quotes.get(sym)
    last = quote.last if quote and quote.last is not None else None

    if pos is None:
        print(f"  {DIM}Position no longer held — decision was moot or already actioned.{RESET}")
        print(f"  Journaled old stop:  {journaled_old_stop:>8.2f}")
        print(f"  Journaled new stop:  {journaled_new_stop:>8.2f}")
        print(f"  Journaled T2 target: {journaled_target:>8.2f}")
        return

    entry = pos.entry_price
    target = pos.target_price
    original_stop = pos.original_stop_price
    qty = pos.broker_position_qty

    # Sanity checks (the four invariants we want every decision to satisfy).
    breakeven_matches_entry = abs(journaled_new_stop - entry) < 0.02
    stop_is_tightening = journaled_new_stop > journaled_old_stop
    stop_below_target = journaled_new_stop < (journaled_target or target)
    market_above_new_stop = last is not None and last > journaled_new_stop

    # Risk geometry.
    initial_risk_per_share = entry - original_stop if entry and original_stop else 0.0
    reward_remaining = target - journaled_new_stop if target else 0.0
    rr_remaining = (reward_remaining / initial_risk_per_share
                    if initial_risk_per_share > 0 else None)

    print(f"  Qty held:            {qty:>8}")
    print(f"  Entry price:         {entry:>8.2f}  (from Mongo trade_orders)")
    print(f"  Original stop:       {original_stop:>8.2f}  "
          f"({(original_stop - entry) / entry * 100:+.2f}% from entry)")
    print(f"  Old stop (journal):  {journaled_old_stop:>8.2f}")
    print(f"  {BOLD}New stop (proposed): {journaled_new_stop:>8.2f}{RESET}  "
          f"{_color('= entry ✓' if breakeven_matches_entry else '≠ entry ✗', breakeven_matches_entry, use_color)}")
    print(f"  T2 target:           {target:>8.2f}  "
          f"({(target - entry) / entry * 100:+.2f}% from entry)")
    if last is not None:
        gap_pct = (last - journaled_new_stop) / journaled_new_stop * 100
        print(f"  Last (Tiingo):       {last:>8.2f}  "
              f"({_color(f'+{gap_pct:.2f}% above new stop ✓' if market_above_new_stop else f'{gap_pct:+.2f}% — AT/BELOW new stop ✗', market_above_new_stop, use_color)})")
    else:
        print(f"  Last (Tiingo):           —  (no quote)")
    if rr_remaining is not None:
        print(f"  Reward remaining:    {reward_remaining:>8.2f}  "
              f"({rr_remaining:.2f} R left to T2)")

    checks = [
        ("tightening (new > old)", stop_is_tightening),
        ("below T2 target", stop_below_target),
        ("matches entry (breakeven rule)", breakeven_matches_entry),
        ("market above new stop", market_above_new_stop if last is not None else None),
    ]
    failed = [name for name, ok in checks if ok is False]
    none_known = [name for name, ok in checks if ok is None]
    if not failed and not none_known:
        print(f"  {_color('✓ all checks pass — decision matches manual rule', True, use_color)}")
    elif failed:
        print(f"  {_color('✗ FAILED: ' + ', '.join(failed), False, use_color)}")
    else:
        print(f"  {DIM}(market check skipped: no Tiingo quote){RESET}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=None,
                        help="UTC date YYYY-MM-DD (default: today UTC).")
    parser.add_argument("--no-color", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)sZ %(levelname)s %(name)s: %(message)s",
    )
    use_color = (not args.no_color) and sys.stdout.isatty()

    date_str = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = _latest_would_advance_rows(date_str)
    print(f"{BOLD}=== BH Swing decision review for {date_str} "
          f"({len(rows)} unique decision(s)) ==={RESET}")
    if not rows:
        print(f"  {DIM}No would_advance_stop events for that date.{RESET}")
        return 0

    s = get_settings()
    client = IBKRClient(config=IBKRConfig(
        host=s.ibkr_host, port=s.ibkr_port,
        client_id=DEFAULT_CLIENT_ID, read_only=True,
    ))
    try:
        positions = client.get_positions()
        open_trades = client.get_open_trades()
        container = create_app_container()
        trade_orders = container.get_database()["trade_orders"]
        build = position_state.build_managed_positions(
            positions, list(open_trades), trade_orders,
        )
        managed_by_symbol = {p.symbol: p for p in build.managed}

        symbols = sorted({str(r.get("symbol", "")) for r in rows})
        quotes = _fetch_tiingo_last_prices(symbols)

        for row in rows:
            _print_review_block(row, managed_by_symbol, quotes, use_color)
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
