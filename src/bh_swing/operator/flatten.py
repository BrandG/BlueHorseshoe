"""Emergency flatten — close open swing positions and cancel their brackets.

Defaults to dry-run. ``--execute`` mutates. Operator tool for the times
when the autonomous trader is misbehaving and you want everything out
right now. Closing order is worst-P&L-first by default (cutting losers
stops the bleed). Capped by ``--max-closes`` to keep blast radius bounded.

Mirrors ``src/bh_ftmo_flatten.py`` in shape — same flags, same journal
format — so muscle memory transfers.

Each close:
  1. Cancel every working order for the symbol (entry + TP + stop legs)
  2. Submit a market SELL for the full position quantity
  3. Journal the action
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from bluehorseshoe.core.config import REPO_ROOT, get_settings
from bluehorseshoe.data.ibkr_client import IBKRClient, IBKRConfig

logger = logging.getLogger("bh_swing.flatten")

JOURNAL_PATH = os.path.join(REPO_ROOT, "src", "logs", "bh_swing_flatten_journal.csv")
JOURNAL_FIELDS = [
    "ts_utc", "run_mode", "event", "symbol", "qty", "avg_cost",
    "unrealized_pnl", "cancelled_order_ids", "market_order_id", "note",
]

DEFAULT_MAX_CLOSES = 10
DEFAULT_CLIENT_ID = int(os.environ.get("BH_SWING_CLIENT_ID", "7"))


@dataclass
class PositionSummary:
    symbol: str
    qty: int
    avg_cost: float
    last_price: float
    unrealized_pnl: float


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _journal(row: dict) -> None:
    os.makedirs(os.path.dirname(JOURNAL_PATH), exist_ok=True)
    new = not os.path.exists(JOURNAL_PATH)
    with open(JOURNAL_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=JOURNAL_FIELDS)
        if new:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in JOURNAL_FIELDS})


def _build_summaries(client: IBKRClient) -> list[PositionSummary]:
    """Snapshot positions and decorate with last-price + unrealized P&L."""
    positions = client.get_positions()
    out: list[PositionSummary] = []
    for p in positions:
        qty = float(p.get("position", 0) or 0)
        if qty == 0:
            continue
        symbol = str(p.get("symbol", ""))
        avg_cost = float(p.get("avg_cost", 0.0) or 0.0)
        last_price = 0.0
        unrealized = 0.0
        try:
            quote = client.get_quote(symbol)
            last_price = quote.last or quote.close or 0.0
            unrealized = (last_price - avg_cost) * qty
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not quote %s for P&L: %s", symbol, e)
        out.append(PositionSummary(
            symbol=symbol, qty=int(qty), avg_cost=avg_cost,
            last_price=last_price, unrealized_pnl=unrealized,
        ))
    return out


def _orders_for_symbol(open_trades, symbol: str) -> list[int]:
    """Order IDs for every working order touching this symbol."""
    ids: list[int] = []
    for t in open_trades:
        if getattr(t.contract, "symbol", "") != symbol:
            continue
        oid = getattr(t.order, "orderId", None)
        if oid:
            ids.append(int(oid))
    return ids


def _print_table(summaries: list[PositionSummary]) -> None:
    if not summaries:
        print("  (no open positions)")
        return
    print(f"  {'Symbol':<8}{'Qty':>8}{'Avg Cost':>12}{'Last':>10}{'Unrealized':>14}")
    for s in summaries:
        print(
            f"  {s.symbol:<8}{s.qty:>8}{s.avg_cost:>12.2f}"
            f"{s.last_price:>10.2f}{s.unrealized_pnl:>14.2f}"
        )


def run(
    client: IBKRClient,
    *,
    execute: bool,
    max_closes: int,
    sort_by: str,
    symbols_filter: Optional[set[str]] = None,
) -> int:
    """Plan and (optionally) execute a flatten pass.

    Returns the count of positions actually closed (0 in dry-run mode).
    """
    run_mode = "live" if execute else "dry-run"
    summaries = _build_summaries(client)
    if symbols_filter:
        summaries = [s for s in summaries if s.symbol in symbols_filter]

    print(f"=== bh_swing flatten ({'EXECUTE' if execute else 'DRY-RUN'}) ===")
    print(f"Sort: {sort_by}  max_closes={max_closes}  positions={len(summaries)}")
    print()

    if sort_by == "worst":
        summaries.sort(key=lambda s: s.unrealized_pnl)
    elif sort_by == "best":
        summaries.sort(key=lambda s: s.unrealized_pnl, reverse=True)
    elif sort_by == "biggest":
        summaries.sort(key=lambda s: abs(s.qty * s.last_price), reverse=True)
    else:
        raise ValueError(f"unknown sort_by: {sort_by!r}")

    plan = summaries[:max_closes]
    print("Plan:")
    _print_table(plan)
    print()

    if not plan:
        print("Nothing to close.")
        return 0

    if not execute:
        for s in plan:
            _journal({
                "ts_utc": _now_utc_iso(), "run_mode": run_mode,
                "event": "would_close", "symbol": s.symbol, "qty": s.qty,
                "avg_cost": f"{s.avg_cost:.2f}",
                "unrealized_pnl": f"{s.unrealized_pnl:.2f}",
                "note": f"sort_by={sort_by}",
            })
        print("(dry-run; no orders sent. Pass --execute to actually close.)")
        return 0

    closed = 0
    for s in plan:
        # Fresh snapshot for each iteration so we react to broker truth
        # (canceller will refuse orders that already auto-cancelled).
        open_trades = client.get_open_trades()
        order_ids = _orders_for_symbol(open_trades, s.symbol)
        cancelled: list[int] = []
        for oid in order_ids:
            result = client.cancel_order(oid)
            if result.get("status") == "cancelling":
                cancelled.append(oid)
            else:
                logger.warning(
                    "Cancel of order %s for %s failed: %s",
                    oid, s.symbol, result.get("error"),
                )

        # Close direction is opposite the position sign.
        action = "SELL" if s.qty > 0 else "BUY"
        result = client.place_market_order(s.symbol, action, abs(s.qty))
        mkt_order_id = result.get("order_id", 0)
        if result.get("status") == "submitted":
            closed += 1
            _journal({
                "ts_utc": _now_utc_iso(), "run_mode": run_mode,
                "event": "position_flattened", "symbol": s.symbol, "qty": s.qty,
                "avg_cost": f"{s.avg_cost:.2f}",
                "unrealized_pnl": f"{s.unrealized_pnl:.2f}",
                "cancelled_order_ids": "|".join(str(i) for i in cancelled),
                "market_order_id": str(mkt_order_id),
                "note": f"sort_by={sort_by} action={action}",
            })
            print(f"  closed {s.symbol} qty={s.qty} mkt_order_id={mkt_order_id}")
        else:
            _journal({
                "ts_utc": _now_utc_iso(), "run_mode": run_mode,
                "event": "flatten_failed", "symbol": s.symbol, "qty": s.qty,
                "note": result.get("error", ""),
            })
            print(f"  ERROR closing {s.symbol}: {result.get('error')}")

    print()
    print(f"Closed {closed}/{len(plan)} positions.")
    return closed


def _build_client() -> IBKRClient:
    s = get_settings()
    return IBKRClient(config=IBKRConfig(
        host=s.ibkr_host, port=s.ibkr_port,
        client_id=DEFAULT_CLIENT_ID,
        read_only=False,
    ))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="BH Swing emergency flatten.")
    parser.add_argument("--execute", action="store_true",
                        help="Actually close positions. Default is dry-run.")
    parser.add_argument("--max-closes", type=int, default=DEFAULT_MAX_CLOSES,
                        help=f"Hard cap on positions closed (default {DEFAULT_MAX_CLOSES}).")
    parser.add_argument("--sort", choices=("worst", "best", "biggest"), default="worst",
                        help="Close order. worst = lowest unrealized P&L first.")
    parser.add_argument("--symbols", default="",
                        help="Comma-separated list to restrict to these symbols.")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)sZ %(levelname)s %(name)s: %(message)s",
    )

    symbols_filter = None
    if args.symbols:
        symbols_filter = {s.strip().upper() for s in args.symbols.split(",") if s.strip()}

    client = _build_client()
    try:
        run(
            client,
            execute=args.execute,
            max_closes=args.max_closes,
            sort_by=args.sort,
            symbols_filter=symbols_filter,
        )
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
