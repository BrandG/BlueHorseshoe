"""BH Live — read-only snapshot of the LIVE IBKR account.

Connects briefly to the `ib-gateway-live` container (started on demand
by `main.py -s --live`), pulls account summary, positions, working
orders, and live last-prices, prints them, then exits. Never mutates
anything — the live Gateway is also pinned to READ_ONLY_API=yes as a
defense-in-depth measure.

Run directly (assumes ib-gateway-live is already up):
  ./run.sh python src/bh_live_status.py
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from bluehorseshoe.data.ibkr_client import IBKRClient, IBKRConfig, QuoteData

logger = logging.getLogger("bh_live.status")

DEFAULT_HOST = os.environ.get("IBKR_HOST_LIVE", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("IBKR_PORT_LIVE", "4011"))
DEFAULT_CLIENT_ID = int(os.environ.get("IBKR_CLIENT_ID_LIVE", "11"))

GREEN = "\033[32m"
RED = "\033[31m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _money(v) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v)


def _color_pnl(pnl: float | None, text: str, use_color: bool) -> str:
    if not use_color or pnl is None:
        return text
    if pnl > 0:
        return f"{GREEN}{text}{RESET}"
    if pnl < 0:
        return f"{RED}{text}{RESET}"
    return f"{DIM}{text}{RESET}"


def _print_account(account: dict) -> None:
    acct = account.get("account_id", "") or "(unknown)"
    netliq = _money(account.get("net_liquidation", 0))
    buying = _money(account.get("buying_power", 0))
    available = _money(account.get("available_funds", 0))
    gross = _money(account.get("gross_position_value", 0))
    print(f"{BOLD}Account {acct}{RESET}  "
          f"NetLiq {netliq}   BuyingPower {buying}   "
          f"Available {available}   GrossPos {gross}")


def _print_positions(positions: list[dict], quotes: dict[str, QuoteData],
                     use_color: bool) -> None:
    rows = [p for p in positions if float(p.get("position", 0) or 0) != 0]
    print(f"\n{BOLD}=== Positions ({len(rows)}) ==={RESET}")
    if not rows:
        print("  (none)")
        return
    print(f"  {'Symbol':<8}{'Type':<5}{'Qty':>10}{'AvgCost':>12}"
          f"{'Last':>12}{'MktValue':>14}{'UnrealP&L':>14}{'P&L%':>9}")
    total_cost = 0.0
    total_mkt = 0.0
    for p in rows:
        sym = str(p.get("symbol", ""))
        ctype = p.get("contract_type", "")
        qty = float(p.get("position", 0))
        avg = float(p.get("avg_cost", 0) or 0)
        q = quotes.get(sym)
        last = q.last if (q and q.last is not None) else None

        cost_basis = qty * avg
        if last is not None:
            mkt_value = qty * last
            unreal = mkt_value - cost_basis
            pct = (unreal / cost_basis * 100.0) if cost_basis else None
            total_cost += cost_basis
            total_mkt += mkt_value
            last_s = f"{last:,.2f}"
            mkt_s = _money(mkt_value)
            pnl_s = f"{unreal:+,.2f}"
            pct_s = f"{pct:+.2f}%" if pct is not None else "—"
            pnl_colored = _color_pnl(unreal, pnl_s, use_color)
            pct_colored = _color_pnl(unreal, pct_s, use_color)
        else:
            last_s = "—"
            mkt_s = "—"
            pnl_colored = "—"
            pct_colored = "—"

        print(f"  {sym:<8}{ctype:<5}{qty:>10.0f}{avg:>12,.2f}"
              f"{last_s:>12}{mkt_s:>14}{pnl_colored:>23}{pct_colored:>18}")

    if total_cost:
        total_pnl = total_mkt - total_cost
        total_pct = total_pnl / total_cost * 100.0
        tot_s = f"{total_pnl:+,.2f}"
        pct_s = f"{total_pct:+.2f}%"
        print(f"  {'':<8}{'':<5}{'':<10}{'':<12}{'TOTAL':>12}"
              f"{_money(total_mkt):>14}"
              f"{_color_pnl(total_pnl, tot_s, use_color):>23}"
              f"{_color_pnl(total_pnl, pct_s, use_color):>18}")


def _print_open_orders(open_trades: list) -> None:
    print(f"\n{BOLD}=== Working Orders ==={RESET}")
    if not open_trades:
        print("  (none)")
        return
    print(f"  {'Symbol':<8}{'Side':<5}{'Qty':>8}  {'Type':<5}{'Price':>12}"
          f"  {'Aux':>10}  {'Status':<14}OrderId")
    for t in open_trades:
        try:
            sym = getattr(t.contract, "symbol", "?")
            action = getattr(t.order, "action", "") or ""
            qty = float(getattr(t.order, "totalQuantity", 0) or 0)
            otype = getattr(t.order, "orderType", "") or ""
            lmt = float(getattr(t.order, "lmtPrice", 0.0) or 0.0)
            aux = float(getattr(t.order, "auxPrice", 0.0) or 0.0)
            status = getattr(t.orderStatus, "status", "") or ""
            oid = getattr(t.order, "orderId", "")
            lmt_s = f"{lmt:,.2f}" if lmt else "—"
            aux_s = f"{aux:,.2f}" if aux else "—"
            print(f"  {sym:<8}{action:<5}{int(qty):>8}  "
                  f"{otype:<5}{lmt_s:>12}  {aux_s:>10}  "
                  f"{status:<14}{oid}")
        except Exception as e:  # noqa: BLE001
            print(f"  (render error: {e})")


def snapshot(host: str, port: int, client_id: int, use_color: bool) -> int:
    client = IBKRClient(config=IBKRConfig(
        host=host, port=port, client_id=client_id, read_only=True,
    ))
    try:
        account = client.get_account_summary()
        positions = client.get_positions()
        open_trades = client.get_open_trades()

        held = sorted({
            str(p.get("symbol", "")) for p in positions
            if float(p.get("position", 0) or 0) != 0
            and p.get("contract_type", "") == "STK"
            and p.get("symbol")
        })
        quotes_list = client.get_quotes(held) if held else []
        quotes = {q.symbol: q for q in quotes_list}

        _print_account(account)
        _print_positions(positions, quotes, use_color)
        _print_open_orders(open_trades)
        return 0
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only snapshot of the LIVE IBKR account.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--client-id", type=int, default=DEFAULT_CLIENT_ID)
    parser.add_argument("--no-color", action="store_true",
                        help="Disable ANSI color output.")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)sZ %(levelname)s %(name)s: %(message)s",
    )

    use_color = (not args.no_color) and sys.stdout.isatty()
    try:
        return snapshot(args.host, args.port, args.client_id, use_color)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR connecting to live Gateway at {args.host}:{args.port}: "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
