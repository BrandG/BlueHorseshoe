"""BH FTMO operator tool — close open positions until margin utilization
drops below a target.

Closes positions in a chosen order (default: worst unrealized P&L first,
since cutting losers stops the bleed and frees margin) one at a time,
refetching account state after each close so the loop reacts to the
real new utilization rather than estimates.

Defaults to dry-run. Pass --execute to actually close.

Examples:
  ./run.sh python src/bh_ftmo_flatten.py
        # dry-run, target=25%, worst-loser-first

  ./run.sh python src/bh_ftmo_flatten.py --target 0.20 --execute
        # actually close until margin util ≤ 20%

  ./run.sh python src/bh_ftmo_flatten.py --strategy biggest --max-closes 5
        # close at most the 5 largest-margin positions (dry-run)
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from bh_ftmo.trading.oanda_trader import (
    OandaTrader,
    OandaTraderConfig,
    OandaTraderError,
)
from bh_ftmo.trading.safety import margin_utilization

REPO_ROOT = Path(__file__).resolve().parents[2]  # src/bud/<this> -> repo root
JOURNAL_PATH = REPO_ROOT / "src" / "logs" / "bh_ftmo_flatten_journal.csv"

DEFAULT_TARGET_UTIL = 0.25
DEFAULT_MAX_CLOSES = 30
SLEEP_BETWEEN_CLOSES_SEC = 0.5

LOG = logging.getLogger("bh_ftmo.flatten")

JOURNAL_FIELDS = [
    "ts_utc", "run_mode", "event", "instrument", "side", "units",
    "avg_price", "margin_used", "unrealized_pl",
    "nav_before", "margin_util_before",
    "nav_after", "margin_util_after",
    "target_util", "note",
]


def _append_journal_row(row: dict) -> None:
    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    new_file = not JOURNAL_PATH.exists()
    with open(JOURNAL_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=JOURNAL_FIELDS)
        if new_file:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in JOURNAL_FIELDS})


def _summarize_position(p: dict) -> dict:
    long_u = int(p["long"]["units"])
    short_u = int(p["short"]["units"])
    if long_u != 0:
        side = "long"
        units = long_u
        avg_price = float(p["long"]["averagePrice"])
    elif short_u != 0:
        side = "short"
        units = short_u
        avg_price = float(p["short"]["averagePrice"])
    else:
        side = "flat"
        units = 0
        avg_price = 0.0
    return {
        "instrument": p["instrument"],
        "side": side,
        "units": units,
        "avg_price": avg_price,
        "margin_used": float(p.get("marginUsed", 0.0)),
        "unrealized_pl": float(p.get("unrealizedPL", 0.0)),
    }


def _sort_key(strategy: str):
    """Return a sort key fn for the chosen close-order strategy.

    worst   — most-negative unrealized P&L first (cut losers)
    best    — most-positive unrealized P&L first (bank winners)
    biggest — largest margin commitment first (free the most margin per close)
    """
    if strategy == "worst":
        return lambda r: r["unrealized_pl"]
    if strategy == "best":
        return lambda r: -r["unrealized_pl"]
    if strategy == "biggest":
        return lambda r: -r["margin_used"]
    raise ValueError(f"unknown strategy {strategy!r}")


def run(*, target_util: float, strategy: str, max_closes: int,
        execute: bool) -> int:
    try:
        cfg = OandaTraderConfig.from_env()
    except OandaTraderError as exc:
        LOG.error("OandaTrader config error: %s", exc)
        return 2

    run_mode = "live" if execute else "dry-run"

    with OandaTrader(cfg) as trader:
        try:
            summary = trader.get_account_summary()
            positions = trader.get_open_positions()
        except OandaTraderError as exc:
            LOG.error("Failed to fetch account state: %s", exc)
            return 1

        nav = float(summary.get("NAV", 0.0))
        util = margin_utilization(summary)
        LOG.info("account NAV=%.2f marginUsed=%.2f util=%.1f%% (target=%.1f%%)",
                 nav, float(summary.get("marginUsed", 0.0)),
                 util * 100, target_util * 100)

        if util <= target_util:
            LOG.info("already under target — nothing to do")
            _append_journal_row({
                "ts_utc": datetime.now(UTC).isoformat(),
                "run_mode": run_mode,
                "event": "noop_under_target",
                "nav_before": f"{nav:.2f}",
                "margin_util_before": f"{util:.4f}",
                "target_util": f"{target_util:.4f}",
            })
            return 0

        rows = [_summarize_position(p) for p in positions if int(p["long"]["units"]) != 0 or int(p["short"]["units"]) != 0]
        rows.sort(key=_sort_key(strategy))

        LOG.info("close-order plan (%s): %d candidate positions", strategy, len(rows))

        # Dry-run preview: simulate by subtracting marginUsed from running total
        sim_margin = float(summary.get("marginUsed", 0.0))
        sim_nav = nav
        n_simulated = 0
        for r in rows:
            if n_simulated >= max_closes:
                break
            sim_util_before = sim_margin / sim_nav if sim_nav > 0 else float("inf")
            if sim_util_before <= target_util:
                break
            sim_margin -= r["margin_used"]
            # Realizing the position moves NAV by 0 (NAV already includes unrealized PL),
            # but balance moves by unrealized_pl. NAV stays roughly stable.
            sim_util_after = sim_margin / sim_nav if sim_nav > 0 else 0.0
            n_simulated += 1
            LOG.info(
                "  [%2d] %s %s units=%d margin=$%.2f unrealPL=$%+.2f → util %.1f%% → %.1f%%",
                n_simulated, r["side"][0].upper(), r["instrument"],
                r["units"], r["margin_used"], r["unrealized_pl"],
                sim_util_before * 100, sim_util_after * 100,
            )
            if not execute:
                _append_journal_row({
                    "ts_utc": datetime.now(UTC).isoformat(),
                    "run_mode": run_mode,
                    "event": "would_close",
                    "instrument": r["instrument"],
                    "side": r["side"],
                    "units": str(r["units"]),
                    "avg_price": f"{r['avg_price']:.5f}",
                    "margin_used": f"{r['margin_used']:.2f}",
                    "unrealized_pl": f"{r['unrealized_pl']:.2f}",
                    "nav_before": f"{sim_nav:.2f}",
                    "margin_util_before": f"{sim_util_before:.4f}",
                    "margin_util_after": f"{sim_util_after:.4f}",
                    "target_util": f"{target_util:.4f}",
                })

        if not execute:
            LOG.info("dry-run: would close %d position(s); pass --execute to act", n_simulated)
            return 0

        # Live close loop — refetch state after each close so we react to truth.
        n_closed = 0
        for r in rows:
            if n_closed >= max_closes:
                LOG.info("reached --max-closes=%d cap", max_closes)
                break

            try:
                summary = trader.get_account_summary()
            except OandaTraderError as exc:
                LOG.error("failed to refetch summary: %s", exc)
                return 1
            nav_now = float(summary.get("NAV", 0.0))
            util_now = margin_utilization(summary)
            if util_now <= target_util:
                LOG.info("target reached: util=%.1f%% ≤ %.1f%%",
                         util_now * 100, target_util * 100)
                break

            base = {
                "ts_utc": datetime.now(UTC).isoformat(),
                "run_mode": run_mode,
                "instrument": r["instrument"],
                "side": r["side"],
                "units": str(r["units"]),
                "avg_price": f"{r['avg_price']:.5f}",
                "margin_used": f"{r['margin_used']:.2f}",
                "unrealized_pl": f"{r['unrealized_pl']:.2f}",
                "nav_before": f"{nav_now:.2f}",
                "margin_util_before": f"{util_now:.4f}",
                "target_util": f"{target_util:.4f}",
            }

            LOG.info("CLOSE %s %s units=%d unrealPL=$%+.2f (util=%.1f%%)",
                     r["side"].upper(), r["instrument"], r["units"],
                     r["unrealized_pl"], util_now * 100)
            try:
                trader.close_position(r["instrument"], side=r["side"])
            except OandaTraderError as exc:
                LOG.error("close failed for %s: %s", r["instrument"], exc)
                _append_journal_row({**base, "event": "close_failed", "note": str(exc)[:200]})
                continue

            n_closed += 1
            try:
                post = trader.get_account_summary()
                util_after = margin_utilization(post)
                nav_after = float(post.get("NAV", 0.0))
            except OandaTraderError:
                util_after = float("nan")
                nav_after = float("nan")

            _append_journal_row({
                **base,
                "event": "closed",
                "nav_after": f"{nav_after:.2f}",
                "margin_util_after": f"{util_after:.4f}",
            })

            # Small pause to let OANDA settle.
            import time
            time.sleep(SLEEP_BETWEEN_CLOSES_SEC)

        LOG.info("done: closed %d position(s)", n_closed)
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Close open OANDA paper positions to reduce margin utilization")
    parser.add_argument("--target", type=float, default=DEFAULT_TARGET_UTIL,
                        help=f"target margin utilization fraction (default {DEFAULT_TARGET_UTIL})")
    parser.add_argument("--strategy", choices=("worst", "best", "biggest"), default="worst",
                        help="close-order: worst (largest losses first), best (winners), biggest (largest margin)")
    parser.add_argument("--max-closes", type=int, default=DEFAULT_MAX_CLOSES,
                        help=f"safety cap on positions closed in one run (default {DEFAULT_MAX_CLOSES})")
    parser.add_argument("--execute", action="store_true",
                        help="actually submit close orders (default: dry-run)")
    args = parser.parse_args(argv)

    if not 0.0 < args.target < 1.0:
        parser.error("--target must be a fraction between 0 and 1")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    return run(target_util=args.target, strategy=args.strategy,
               max_closes=args.max_closes, execute=args.execute)


if __name__ == "__main__":
    raise SystemExit(main())
