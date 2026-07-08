"""BH Swing — operator dashboard (read-only).

Single-screen account + positions + recent journal view. SSH-friendly.
Never mutates anything; pulls fresh state from IBKR and prints it.

Usage:
  python src/bh_swing_status.py                # default: account + positions + last 20 events
  python src/bh_swing_status.py --events 50    # show last 50 journal events
  python src/bh_swing_status.py --no-broker    # journal only (skip IBKR connect)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from bluehorseshoe.core.config import get_settings
from bluehorseshoe.data.ibkr_client import IBKRClient, IBKRConfig

from bh_swing import journal
from bh_swing.trading import reconciler

logger = logging.getLogger("bh_swing.status")

DEFAULT_CLIENT_ID = int(os.environ.get("BH_SWING_CLIENT_ID", "7"))


def _money(v) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v)


def _qty(v) -> str:
    """Format a share/contract quantity, preserving fractional values.

    IBKR supports fractional shares, so a hard int cast (or ``.0f``) silently
    truncates partial positions. Show whole numbers without a decimal point and
    fractional quantities with up to 4 decimals (trailing zeros stripped).
    """
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if f == int(f):
        return str(int(f))
    return f"{f:.4f}".rstrip("0").rstrip(".")


def _print_account(account: dict) -> None:
    print("=== Account ===")
    print(f"  ID                 {account.get('account_id', '') or '(unknown)'}")
    print(f"  Net Liquidation    {_money(account.get('net_liquidation', 0))}")
    print(f"  Settled Cash       {_money(account.get('settled_cash', 0))}")
    print(f"  Available Funds    {_money(account.get('available_funds', 0))}")
    print(f"  Buying Power       {_money(account.get('buying_power', 0))}")
    print(f"  Gross Positions    {_money(account.get('gross_position_value', 0))}")


def _print_positions(positions: list[dict]) -> None:
    print("\n=== Positions ===")
    rows = [p for p in positions if float(p.get("position", 0) or 0) != 0]
    if not rows:
        print("  (none)")
        return
    print(f"  {'Symbol':<10}{'Qty':>10}{'Avg Cost':>14}  Type   Ccy")
    for p in rows:
        print(
            f"  {str(p.get('symbol', '')):<10}"
            f"{_qty(p.get('position', 0)):>10}"
            f"{_money(p.get('avg_cost', 0)):>14}  "
            f"{p.get('contract_type', '')}   "
            f"{p.get('currency', '')}"
        )


def _print_open_orders(open_trades: list) -> None:
    print("\n=== Working Orders ===")
    if not open_trades:
        print("  (none)")
        return
    print(f"  {'Symbol':<8}{'Action':<6}{'Qty':>8}  {'Type':<5}{'Price':>12}  {'Status':<14}OrderId")
    for t in open_trades:
        try:
            sym = getattr(t.contract, "symbol", "?")
            action = getattr(t.order, "action", "") or ""
            qty = getattr(t.order, "totalQuantity", 0)
            otype = getattr(t.order, "orderType", "") or ""
            lmt = float(getattr(t.order, "lmtPrice", 0.0) or 0.0)
            stp = float(getattr(t.order, "auxPrice", 0.0) or 0.0)
            price = lmt if lmt else stp
            status = getattr(t.orderStatus, "status", "") or ""
            oid = getattr(t.order, "orderId", "")
            print(
                f"  {sym:<8}{action:<6}{_qty(qty):>8}  "
                f"{otype:<5}{_money(price) if price else '—':>12}  "
                f"{status:<14}{oid}"
            )
        except Exception as e:  # noqa: BLE001
            print(f"  (render error: {e})")


def _print_journal(limit: int) -> None:
    rows = journal.read_recent(limit=limit)
    print(f"\n=== Recent Journal ({len(rows)} rows) ===")
    if not rows:
        print("  (empty)")
        return
    for r in rows:
        ts = r.get("ts_utc", "")[:19].replace("T", " ")
        event = r.get("event", "")
        sym = r.get("symbol", "")
        side = r.get("side", "")
        qty = r.get("quantity", "")
        price = r.get("price", "")
        note = r.get("note", "")
        print(f"  {ts}  {event:<22} {sym:<6} {side:<5} qty={qty:<6} price={price:<10} {note}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BH Swing status dashboard.")
    parser.add_argument("--events", type=int, default=20,
                        help="Number of recent journal events to print.")
    parser.add_argument("--no-broker", action="store_true",
                        help="Skip IBKR connection; print journal only.")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)sZ %(levelname)s %(name)s: %(message)s",
    )

    if args.no_broker:
        _print_journal(args.events)
        return 0

    s = get_settings()
    client = IBKRClient(config=IBKRConfig(
        host=s.ibkr_host,
        port=s.ibkr_port,
        client_id=DEFAULT_CLIENT_ID,
        read_only=True,
    ))
    try:
        account, positions, open_trades = reconciler.snapshot_account(client)
        _print_account(account)
        _print_positions(positions)
        _print_open_orders(open_trades)
        _print_journal(args.events)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR fetching broker state: {type(e).__name__}: {e}", file=sys.stderr)
        print("\n(Falling back to journal-only view.)", file=sys.stderr)
        _print_journal(args.events)
        return 2
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
