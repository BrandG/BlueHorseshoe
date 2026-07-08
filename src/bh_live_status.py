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
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests

from bluehorseshoe.core.config import REPO_ROOT
from bluehorseshoe.data.ibkr_client import IBKRClient, IBKRConfig, QuoteData

EXECUTIONS_CACHE_PATH = Path(REPO_ROOT) / "src" / "logs" / "ibkr_executions_cache.json"

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


def _load_executions_cache(path: Path) -> dict[str, dict]:
    """Read persisted executions, keyed by exec_id. Empty dict on miss/corruption."""
    if not path.exists():
        return {}
    try:
        with path.open() as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"WARNING: executions cache at {path} unreadable ({e}); "
              "starting fresh.", file=sys.stderr)
        return {}
    return data if isinstance(data, dict) else {}


def _save_executions_cache(path: Path, cache: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as f:
        json.dump(cache, f, default=str, indent=2, sort_keys=True)
    tmp.replace(path)


def _merge_executions_into_cache(
    cache: dict[str, dict], executions: list[dict]
) -> int:
    """Add any unseen exec_ids to the cache. Returns count of new rows."""
    added = 0
    for e in executions:
        eid = e.get("exec_id")
        if not eid or eid in cache:
            continue
        record = dict(e)
        t = record.get("exec_time")
        if hasattr(t, "isoformat"):
            record["exec_time"] = t.isoformat()
        cache[eid] = record
        added += 1
    return added


def _fill_avgs_from_executions(executions: list[dict]) -> dict[str, float]:
    """Compute per-symbol weighted-avg raw fill price (excluding commission).

    Only BOT (buy) side counts toward the long-position cost basis.
    """
    totals: dict[str, list[float]] = {}
    for e in executions:
        if str(e.get("side", "")).lower() != "bot":
            continue
        sym = e.get("symbol")
        qty = float(e.get("quantity", 0) or 0)
        price = float(e.get("price", 0) or 0)
        if not sym or qty <= 0 or price <= 0:
            continue
        agg = totals.setdefault(sym, [0.0, 0.0])  # [sum_qty*price, sum_qty]
        agg[0] += qty * price
        agg[1] += qty
    return {s: v[0] / v[1] for s, v in totals.items() if v[1] > 0}


def _print_positions(positions: list[dict], quotes: dict[str, QuoteData],
                     fill_avgs: dict[str, float], use_color: bool) -> None:
    rows = [p for p in positions if float(p.get("position", 0) or 0) != 0]
    print(f"\n{BOLD}=== Positions ({len(rows)}) ==={RESET}")
    if not rows:
        print("  (none)")
        return
    print(f"  {'Symbol':<8}{'Type':<5}{'Qty':>10}{'FillAvg':>10}{'AvgCost':>10}"
          f"{'Last':>10}{'MktValue':>14}{'UnrealP&L':>14}{'P&L%':>9}")
    total_cost = 0.0
    total_mkt = 0.0
    for p in rows:
        sym = str(p.get("symbol", ""))
        ctype = p.get("contract_type", "")
        qty = float(p.get("position", 0))
        avg = float(p.get("avg_cost", 0) or 0)
        q = quotes.get(sym)
        last = q.last if (q and q.last is not None) else None
        fill = fill_avgs.get(sym)

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

        fill_s = f"{fill:,.2f}" if fill is not None else "—"
        print(f"  {sym:<8}{ctype:<5}{qty:>10g}{fill_s:>10}{avg:>10,.2f}"
              f"{last_s:>10}{mkt_s:>14}{pnl_colored:>23}{pct_colored:>18}")

    if total_cost:
        total_pnl = total_mkt - total_cost
        total_pct = total_pnl / total_cost * 100.0
        tot_s = f"{total_pnl:+,.2f}"
        pct_s = f"{total_pct:+.2f}%"
        print(f"  {'':<8}{'':<5}{'':<10}{'':<10}{'':<10}{'TOTAL':>10}"
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
            print(f"  {sym:<8}{action:<5}{qty:>8g}  "
                  f"{otype:<5}{lmt_s:>12}  {aux_s:>10}  "
                  f"{status:<14}{oid}")
        except Exception as e:  # noqa: BLE001
            print(f"  (render error: {e})")


def _fetch_tiingo_last_prices(symbols: list[str]) -> dict[str, QuoteData]:
    """Get latest US-equity prices from Tiingo's IEX endpoint.

    Used instead of IBKR market data because the read-only secondary user
    doesn't have its own IBKR market data subscription (each IBKR user is
    billed separately for data, per exchange rules). Tiingo is already paid
    for via TIINGO_API_KEY in .env, so no incremental cost.
    """
    api_key = os.environ.get("TIINGO_API_KEY")
    if not api_key or not symbols:
        return {}
    try:
        r = requests.get(
            "https://api.tiingo.com/iex/",
            params={"tickers": ",".join(symbols)},
            headers={"Authorization": f"Token {api_key}"},
            timeout=8,
        )
        r.raise_for_status()
        rows = r.json()
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, QuoteData] = {}
    for row in rows:
        sym = row.get("ticker")
        last = row.get("tngoLast") or row.get("last") or row.get("prevClose")
        if sym and last is not None:
            try:
                out[sym] = QuoteData(symbol=sym, last=float(last))
            except (TypeError, ValueError):
                continue
    return out


def snapshot(host: str, port: int, client_id: int, use_color: bool,
             exec_lookback_days: int) -> int:
    client = IBKRClient(config=IBKRConfig(
        host=host, port=port, client_id=client_id, read_only=True,
    ))
    try:
        account = client.get_account_summary()
        positions = client.get_positions()
        open_trades = client.get_open_trades()
        executions = client.get_executions(
            since=datetime.now() - timedelta(days=exec_lookback_days),
        )
        cache = _load_executions_cache(EXECUTIONS_CACHE_PATH)
        new_count = _merge_executions_into_cache(cache, executions)
        if new_count:
            _save_executions_cache(EXECUTIONS_CACHE_PATH, cache)
        fill_avgs = _fill_avgs_from_executions(list(cache.values()))
        print(f"{DIM}FillAvg: {len(cache)} cached fills "
              f"({new_count} new this run) "
              f"from {EXECUTIONS_CACHE_PATH.name}{RESET}")

        held = sorted({
            str(p.get("symbol", "")) for p in positions
            if float(p.get("position", 0) or 0) != 0
            and p.get("contract_type", "") == "STK"
            and p.get("symbol")
        })
        # Tiingo for quotes — see _fetch_tiingo_last_prices for the why.
        quotes = _fetch_tiingo_last_prices(held)

        _print_account(account)
        _print_positions(positions, quotes, fill_avgs, use_color)
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
    parser.add_argument("--exec-lookback-days", type=int, default=1,
                        help="Lookback for the IBKR executions query that "
                             "feeds the FillAvg cache. NOTE: IBKR's "
                             "reqExecutions only returns the current "
                             "session's fills regardless of this value — "
                             "older fills come from the local cache at "
                             "src/logs/ibkr_executions_cache.json.")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)sZ %(levelname)s %(name)s: %(message)s",
    )

    use_color = (not args.no_color) and sys.stdout.isatty()
    try:
        return snapshot(args.host, args.port, args.client_id, use_color,
                        args.exec_lookback_days)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR connecting to live Gateway at {args.host}:{args.port}: "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
