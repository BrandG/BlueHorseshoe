"""Manage open-position state shared by bh_lite and bh_briefing_ftmo.

Both signal generators read bh_lite_positions.json for:
  - skip pairs already open
  - cluster-suppression (an open NZDCAD blocks new CADCHF)
  - daily-risk budget tracking

This helper keeps that file honest. Three commands:

  list                   — print current open positions
  add FTMO_SYMBOL        — read bh_briefing_ftmo_orders.json (or
                           bh_lite_orders.json), find the order for
                           FTMO_SYMBOL, append it to positions with
                           today's date. Manual override via --entry
                           --stop --target --lots --side flags.
  close FTMO_SYMBOL      — remove from positions, append a record
                           to bh_positions_closed.json with close
                           timestamp + optional --close-price / --pnl

Usage:
  ./run.sh python src/bh_positions.py list
  ./run.sh python src/bh_positions.py add NZDCHF.sim
  ./run.sh python src/bh_positions.py add EURJPY.sim --entry 162.45 --stop 164.07 --target 161.64 --lots 0.06 --side sell
  ./run.sh python src/bh_positions.py close NZDCAD.sim --close-price 0.8200 --pnl +49.20
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
POSITIONS_PATH = REPO_ROOT / "src" / "bh_lite_positions.json"
CLOSED_LOG_PATH = REPO_ROOT / "src" / "bh_positions_closed.json"
BRIEFING_ORDERS_PATH = REPO_ROOT / "src" / "bh_briefing_ftmo_orders.json"
BH_LITE_ORDERS_PATH = REPO_ROOT / "src" / "bh_lite_orders.json"
LITE_CONFIG_PATH = REPO_ROOT / "src" / "bh_lite_config.json"


def _load_instrument_map() -> dict[str, dict]:
    """Index bh_lite_config instruments by FTMO .sim symbol."""
    if not LITE_CONFIG_PATH.exists():
        return {}
    cfg = json.loads(LITE_CONFIG_PATH.read_text(encoding="utf-8"))
    return {inst["ftmo"]: inst for inst in cfg.get("instruments", [])}


def compute_risk_usd(ftmo_symbol: str, entry: float, stop: float,
                     lots: float, instrument_map: dict[str, dict] | None = None) -> float | None:
    """Forex risk: lots × pips_at_risk × dollar_per_pip_per_lot.
    Returns None if the instrument isn't in the config.
    """
    if instrument_map is None:
        instrument_map = _load_instrument_map()
    inst = instrument_map.get(ftmo_symbol)
    if inst is None:
        return None
    pip_size = float(inst.get("pip_size", 0))
    dpp = float(inst.get("dollar_per_pip_per_lot", 0))
    if pip_size <= 0 or dpp <= 0:
        return None
    risk_in_pips = abs(entry - stop) / pip_size
    return round(risk_in_pips * dpp * float(lots), 2)


def _backheal_positions(positions: list[dict]) -> tuple[list[dict], bool]:
    """Fill in risk_usd for any position missing it (or with risk_usd=0).
    Returns (positions, changed) so callers can write back when changed.
    """
    inst_map = _load_instrument_map()
    changed = False
    for p in positions:
        if p.get("risk_usd"):
            continue
        risk = compute_risk_usd(
            p.get("ftmo_symbol", ""),
            float(p["entry"]), float(p["stop"]), float(p["lots"]),
            instrument_map=inst_map,
        )
        if risk is not None:
            p["risk_usd"] = risk
            changed = True
    return positions, changed


def load_positions() -> list[dict]:
    if not POSITIONS_PATH.exists():
        return []
    raw = POSITIONS_PATH.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    positions = json.loads(raw)
    positions, changed = _backheal_positions(positions)
    if changed:
        save_positions(positions)
    return positions


def save_positions(positions: list[dict]) -> None:
    POSITIONS_PATH.write_text(
        json.dumps(positions, indent=2) + "\n", encoding="utf-8")


def append_closed(record: dict) -> None:
    log = []
    if CLOSED_LOG_PATH.exists():
        raw = CLOSED_LOG_PATH.read_text(encoding="utf-8").strip()
        if raw:
            log = json.loads(raw)
    log.append(record)
    CLOSED_LOG_PATH.write_text(
        json.dumps(log, indent=2) + "\n", encoding="utf-8")


def cmd_list(_args: argparse.Namespace) -> int:
    positions = load_positions()
    if not positions:
        print("(no open positions)")
        return 0
    total_risk = sum(float(p.get("risk_usd", 0)) for p in positions)
    print(f"Open positions ({len(positions)}, total risk ${total_risk:.2f}):")
    print(f"  {'FTMO Symbol':<14} {'Side':<5} {'Lots':>6}  "
          f"{'Entry':>9}  {'Stop':>9}  {'Target':>9}  {'Risk$':>8}  {'Opened':<12}")
    for p in positions:
        print(f"  {p['ftmo_symbol']:<14} {p['side']:<5} {p['lots']:>6}  "
              f"{p['entry']:>9}  {p['stop']:>9}  {p.get('target', '—'):>9}  "
              f"${p.get('risk_usd', 0):>6.2f}  {p.get('opened', '?'):<12}")
    return 0


def _find_in_orders(ftmo_symbol: str) -> dict | None:
    """Search bh_briefing_ftmo_orders.json first, then bh_lite_orders.json."""
    for path in (BRIEFING_ORDERS_PATH, BH_LITE_ORDERS_PATH):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        orders = data.get("orders") if isinstance(data, dict) else None
        if not isinstance(orders, list):
            continue
        for order in orders:
            if order.get("ftmo_symbol") == ftmo_symbol:
                return {**order, "_source": str(path.name)}
    return None


def cmd_add(args: argparse.Namespace) -> int:
    positions = load_positions()
    if any(p.get("ftmo_symbol") == args.ftmo_symbol for p in positions):
        print(f"ERROR: {args.ftmo_symbol} already in positions. "
              f"Use 'close' first if reopening.", file=sys.stderr)
        return 2

    # Try to pull from a generated orders.json unless fully manual flags given
    manual = all(v is not None for v in
                 (args.side, args.entry, args.stop, args.lots))
    if manual:
        source = "manual flags"
        side = args.side
        entry = args.entry
        stop = args.stop
        target = args.target if args.target is not None else None
        lots = args.lots
        strategy = args.strategy
        risk_usd = compute_risk_usd(args.ftmo_symbol, entry, stop, lots)
        if risk_usd is None:
            print(f"WARN: no instrument config for {args.ftmo_symbol} — "
                  f"risk_usd will be blank. Add it to bh_lite_config.json "
                  f"or pass --side/--entry/--stop/--lots after editing config.",
                  file=sys.stderr)
    else:
        found = _find_in_orders(args.ftmo_symbol)
        if found is None:
            print(f"ERROR: no order for {args.ftmo_symbol} found in "
                  f"{BRIEFING_ORDERS_PATH.name} or {BH_LITE_ORDERS_PATH.name}. "
                  f"Provide --side --entry --stop --lots to add manually.",
                  file=sys.stderr)
            return 3
        source = found["_source"]
        side = args.side or found.get("side")
        entry = args.entry if args.entry is not None else found.get("entry")
        stop = args.stop if args.stop is not None else found.get("stop")
        target = args.target if args.target is not None else found.get("target")
        lots = args.lots if args.lots is not None else found.get("lots")
        strategy = args.strategy or found.get("strategy")
        risk_usd = found.get("risk_usd")

    if any(v is None for v in (side, entry, stop, lots)):
        print(f"ERROR: incomplete fields after merge "
              f"(side={side}, entry={entry}, stop={stop}, lots={lots})",
              file=sys.stderr)
        return 4

    today = args.opened or date.today().isoformat()
    new_position = {
        "ftmo_symbol": args.ftmo_symbol,
        "side": side,
        "entry": float(entry),
        "stop": float(stop),
        "target": float(target) if target is not None else None,
        "lots": float(lots),
        "risk_usd": float(risk_usd) if risk_usd is not None else None,
        "opened": today,
    }
    if strategy:
        new_position["strategy"] = strategy
    # Drop Nones for cleanliness
    new_position = {k: v for k, v in new_position.items() if v is not None}
    positions.append(new_position)
    save_positions(positions)
    print(f"Added {args.ftmo_symbol} (source: {source}):")
    for k, v in new_position.items():
        print(f"  {k}: {v}")
    return 0


def cmd_close(args: argparse.Namespace) -> int:
    positions = load_positions()
    match = next((p for p in positions
                  if p.get("ftmo_symbol") == args.ftmo_symbol), None)
    if match is None:
        print(f"ERROR: {args.ftmo_symbol} not in positions.", file=sys.stderr)
        return 2
    positions = [p for p in positions if p is not match]
    save_positions(positions)

    closed_record = {
        **match,
        "closed_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "close_price": args.close_price,
        "pnl_usd": args.pnl,
        "note": args.note,
    }
    closed_record = {k: v for k, v in closed_record.items() if v is not None}
    append_closed(closed_record)
    print(f"Closed {args.ftmo_symbol}. Remaining open positions: {len(positions)}")
    if args.pnl is not None:
        print(f"  Realized P&L: ${args.pnl:+.2f}")
    if args.close_price is not None:
        print(f"  Close price: {args.close_price}")
    print(f"  Archived to {CLOSED_LOG_PATH.name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Manage bh_lite_positions.json (shared by bh_lite + bh_briefing_ftmo)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="show open positions")

    p_add = sub.add_parser("add", help="add a position (from latest orders.json or manual)")
    p_add.add_argument("ftmo_symbol")
    p_add.add_argument("--side", choices=("buy", "sell"))
    p_add.add_argument("--entry", type=float)
    p_add.add_argument("--stop", type=float)
    p_add.add_argument("--target", type=float)
    p_add.add_argument("--lots", type=float)
    p_add.add_argument("--strategy")
    p_add.add_argument("--opened", help="YYYY-MM-DD (default: today)")

    p_close = sub.add_parser("close", help="close a position (archive to closed log)")
    p_close.add_argument("ftmo_symbol")
    p_close.add_argument("--close-price", type=float)
    p_close.add_argument("--pnl", type=float, help="realized P&L in USD")
    p_close.add_argument("--note")

    args = parser.parse_args(argv)
    if getattr(args, "ftmo_symbol", None) and "." not in args.ftmo_symbol:
        args.ftmo_symbol = f"{args.ftmo_symbol}.sim"
    if args.cmd == "list":
        return cmd_list(args)
    if args.cmd == "add":
        return cmd_add(args)
    if args.cmd == "close":
        return cmd_close(args)
    parser.error(f"unknown cmd {args.cmd}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
