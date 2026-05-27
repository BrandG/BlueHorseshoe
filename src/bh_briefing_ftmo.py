"""BH Briefing → FTMO live-order generator.

Wraps bh_briefing.evaluate_fires() to produce manually-placeable FTMO orders:
maps OANDA pairs to FTMO .sim symbols, computes lot sizing per the v2_paper
risk profile (0.5% × $10K = $50/R, max 5 concurrent), applies cluster
suppression from bh_lite_config, and reads bh_lite_positions.json to skip
pairs already open on the live challenge.

Reuses bh_lite's account, risk, instruments, and clusters config so the FTMO
trading envelope stays consistent across the daily-bar (bh_lite) and H4
(this tool) channels. Risk per trade and concurrency cap are overridden to
match v2_paper.

Two cadences:
  - every H4 close (cron, runs after bh_briefing)
  - once-daily summary at 22:30 UTC (replaces/companions bh_lite)

Output:
  - Console table: # | FTMO Symbol | Cluster | Cell | Entry | Stop | Target | Lots | Risk$ | Rank
  - JSON file (bh_briefing_ftmo_orders.json) for clipboard/copy use
  - Position-aware: skips fires on pairs already in bh_lite_positions.json
  - Cluster-aware: suppresses fires whose cluster is occupied by an open
    position OR by an earlier (higher-ranked) fire in the same run
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Import sibling modules (bh_briefing, ftmo_envelope) from the same src/ dir.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bh_briefing import (
    CELLS, CELL_QUALITY_RANK, TP_PCT, STOP_PCT,
    evaluate_fires, _price_precision,
)
from ftmo_envelope import (
    DEFAULT_CONFIG_PATH, DEFAULT_POSITIONS_PATH,
    load_config, load_positions,
    symbol_to_clusters_map,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ORDERS_JSON_PATH = REPO_ROOT / "src" / "bh_briefing_ftmo_orders.json"

# Overrides applied on top of bh_lite_config — matches v2_paper risk envelope
RISK_PER_TRADE_PCT = 0.005    # 0.5% (bh_lite default is 1%)
MAX_CONCURRENT_POSITIONS = 5   # matches v2_paper (bh_lite default is 3)
MAX_DAILY_RISK_PCT = 0.04      # unchanged from bh_lite

LOG = logging.getLogger("bh_briefing.ftmo")


def oanda_to_ftmo(pair: str) -> str:
    """USD_JPY -> USDJPY.sim. FTMO platform convention."""
    return pair.replace("_", "") + ".sim"


def build_instrument_map(config: dict) -> dict[str, dict]:
    """Index instruments by their .ftmo symbol for quick lookup."""
    return {inst["ftmo"]: inst for inst in config["instruments"]}


def round_down_to_lot(lots: float, min_lot: float) -> float:
    """Round lots down to the broker's min-lot increment."""
    if min_lot <= 0 or lots <= 0:
        return 0.0
    return math.floor(lots / min_lot) * min_lot


def compute_lots(entry: float, stop: float, risk_usd: float,
                 instrument: dict) -> tuple[float, float]:
    """Returns (lots, actual_risk_usd). 0.0 if anything degenerate."""
    risk_per_unit = abs(entry - stop)
    if risk_per_unit <= 0:
        return 0.0, 0.0
    pip_size = float(instrument["pip_size"])
    dpp = float(instrument["dollar_per_pip_per_lot"])
    risk_in_pips = risk_per_unit / pip_size
    if risk_in_pips <= 0 or dpp <= 0:
        return 0.0, 0.0
    raw_lots = risk_usd / (risk_in_pips * dpp)
    lots = round_down_to_lot(raw_lots, float(instrument["min_lot"]))
    actual_risk = lots * risk_in_pips * dpp
    return lots, actual_risk


def apply_position_skip(fires: list[dict], positions: list[dict]) -> tuple[list[dict], list[dict]]:
    """Remove fires whose FTMO symbol matches an already-open position."""
    held = {p["ftmo_symbol"] for p in positions}
    kept, skipped = [], []
    for f in fires:
        if f["ftmo_symbol"] in held:
            skipped.append({**f, "skip_reason": "position already open"})
        else:
            kept.append(f)
    return kept, skipped


def apply_cluster_filter(fires: list[dict], clusters: dict[str, list[str]],
                         positions: list[dict]) -> tuple[list[dict], list[dict]]:
    """Suppress fires whose cluster is already occupied — either by an open
    position OR by an earlier (higher-ranked) fire in the same run.

    Fires arrive pre-sorted by CELL_QUALITY_RANK desc, so the first fire in
    any cluster wins it. Sub-cluster matches are checked across ALL clusters
    the fire's symbol belongs to.
    """
    symbol_to_clusters = symbol_to_clusters_map(clusters)
    # Seed with clusters occupied by open positions
    occupied: dict[str, str] = {}
    for p in positions:
        for cluster in symbol_to_clusters.get(p["ftmo_symbol"], []):
            occupied.setdefault(cluster, p["ftmo_symbol"])

    kept, suppressed = [], []
    for f in fires:
        fire_clusters = symbol_to_clusters.get(f["ftmo_symbol"], [])
        blocking = next((c for c in fire_clusters if c in occupied), None)
        if blocking is not None:
            suppressed.append({
                **f,
                "clusters": fire_clusters,
                "skip_reason": f"cluster '{blocking}' held by {occupied[blocking]}",
            })
            continue
        f["clusters"] = fire_clusters
        kept.append(f)
        for c in fire_clusters:
            occupied.setdefault(c, f["ftmo_symbol"])
    return kept, suppressed


def annotate_fires(fires: list[dict], instrument_map: dict[str, dict]) -> list[dict]:
    """Decorate each fire with ftmo_symbol, rank, and instrument info."""
    out = []
    for f in fires:
        ftmo = oanda_to_ftmo(f["pair"])
        inst = instrument_map.get(ftmo)
        if inst is None:
            LOG.warning("no instrument config for %s (%s) — skipping",
                        ftmo, f["pair"])
            continue
        rank = CELL_QUALITY_RANK.get(
            (f["strategy"], f["pair"], f["direction"]), float("-inf"))
        out.append({**f, "ftmo_symbol": ftmo, "instrument": inst,
                    "quality_rank": rank})
    return out


def render_console(annotated: list[dict], suppressed: list[dict],
                   positions: list[dict], account_size: float,
                   daily_risk_used: float, daily_risk_cap: float,
                   now_utc: datetime) -> str:
    lines = []
    lines.append(f"BH Briefing → FTMO  ({now_utc.strftime('%Y-%m-%d %H:%M UTC')})")
    lines.append(f"Account: ${account_size:,.0f}  risk/trade: {RISK_PER_TRADE_PCT*100:.2f}%"
                 f"  max concurrent: {MAX_CONCURRENT_POSITIONS}"
                 f"  daily risk: ${daily_risk_used:,.2f} / ${daily_risk_cap:,.2f}")
    if positions:
        lines.append("")
        lines.append("Open positions (read from bh_lite_positions.json):")
        for p in positions:
            lines.append(f"  {p['ftmo_symbol']:<14} {p['side']:<5} "
                         f"{p['lots']:>5} lots  entry {p['entry']:<9}  "
                         f"stop {p['stop']:<9}  risk ${p.get('risk_usd', 0):>6.2f}  "
                         f"opened {p.get('opened', '?')}")
    lines.append("")
    if not annotated:
        lines.append("No tradeable fires on this bar (after position + cluster filters).")
    else:
        lines.append("== ORDERS TO PLACE ==")
        lines.append(f"  {'#':>2}  {'FTMO Symbol':<14}  {'SIDE':<6}  "
                     f"{'Cluster':<16}  {'Cell':<18}  "
                     f"{'Entry':>10}  {'Stop':>10}  {'Target':>10}  "
                     f"{'Lots':>6}  {'Risk $':>8}  {'Rank':>7}")
        for i, f in enumerate(annotated, 1):
            side = "BUY" if f["direction"] == "long" else "SELL"
            cell_desc = f"{f['strategy']}/{f['entry_mode']}"
            cluster = (f.get("clusters") or [""])[0] or "—"
            precision = f["precision"]
            ent = f"{f['entry']:.{precision}f}"
            stp = f"{f['stop']:.{precision}f}"
            tgt = f"{f['target']:.{precision}f}"

            # Sanity check: geometry must match declared side.
            warn = ""
            if side == "BUY":
                if not (f["target"] > f["entry"] > f["stop"]):
                    warn = "  !! GEOMETRY MISMATCH — review before placing"
            else:  # SELL
                if not (f["target"] < f["entry"] < f["stop"]):
                    warn = "  !! GEOMETRY MISMATCH — review before placing"

            lines.append(f"  {i:>2}  {f['ftmo_symbol']:<14}  {side:<6}  "
                         f"{cluster:<16}  {cell_desc:<18}  "
                         f"{ent:>10}  {stp:>10}  {tgt:>10}  "
                         f"{f['lots']:>6.2f}  ${f['actual_risk']:>6.2f}  "
                         f"{f['quality_rank']:>+6.3f}{warn}")
        lines.append("")
        lines.append("  SIDE column: BUY = long (target > entry > stop),  "
                     "SELL = short (target < entry < stop)")
    if suppressed:
        lines.append("")
        lines.append("== SUPPRESSED ==")
        for f in suppressed:
            cell_desc = f"{f['strategy']:>9}/{f['direction']:<5}"
            lines.append(f"  {f.get('ftmo_symbol', f['pair']):<14}  "
                         f"{cell_desc:<22}  {f['skip_reason']}")
    return "\n".join(lines)


def run(*, dry_run: bool = False) -> int:
    config = load_config(DEFAULT_CONFIG_PATH)
    positions = load_positions(DEFAULT_POSITIONS_PATH)
    instrument_map = build_instrument_map(config)
    clusters = config.get("clusters", {})
    account_size = float(config["account"]["size"])

    # Position-derived state
    daily_risk_used = sum(float(p.get("risk_usd", 0.0)) for p in positions)
    daily_risk_cap = account_size * MAX_DAILY_RISK_PCT
    remaining_daily = max(0.0, daily_risk_cap - daily_risk_used)
    remaining_slots = max(0, MAX_CONCURRENT_POSITIONS - len(positions))
    risk_per_trade_usd = account_size * RISK_PER_TRADE_PCT

    # Pull fires from bh_briefing (already in CELL_QUALITY_RANK descending order)
    fires_raw, _, _ = evaluate_fires()
    fires = annotate_fires(fires_raw, instrument_map)

    fires, pos_skipped = apply_position_skip(fires, positions)
    fires, cluster_suppressed = apply_cluster_filter(fires, clusters, positions)

    # Cap by remaining concurrent slots
    accepted = []
    for f in fires:
        if len(accepted) >= remaining_slots:
            cluster_suppressed.append({
                **f,
                "skip_reason": f"over max concurrent ({MAX_CONCURRENT_POSITIONS})",
            })
            continue
        if remaining_daily <= 0:
            cluster_suppressed.append({
                **f, "skip_reason": "daily risk budget exhausted"})
            continue
        lots, actual_risk = compute_lots(
            f["entry"], f["stop"], risk_per_trade_usd, f["instrument"])
        if lots <= 0:
            cluster_suppressed.append({
                **f, "skip_reason": "computed 0 lots"})
            continue
        accepted.append({**f, "lots": lots, "actual_risk": actual_risk})
        remaining_daily -= actual_risk

    suppressed = pos_skipped + cluster_suppressed
    now_utc = datetime.now(UTC)
    print(render_console(accepted, suppressed, positions, account_size,
                         daily_risk_used, daily_risk_cap, now_utc))

    # Write structured JSON for copy/paste into FTMO platform
    if not dry_run:
        orders_payload = {
            "generated_utc": now_utc.isoformat(),
            "account_size": account_size,
            "risk_per_trade_pct": RISK_PER_TRADE_PCT,
            "max_concurrent": MAX_CONCURRENT_POSITIONS,
            "daily_risk_used_before": daily_risk_used,
            "daily_risk_cap": daily_risk_cap,
            "open_positions": positions,
            "orders": [
                {
                    "ftmo_symbol": f["ftmo_symbol"],
                    "side": "buy" if f["direction"] == "long" else "sell",
                    "entry_mode": f["entry_mode"],
                    "entry": round(f["entry"], f["precision"]),
                    "stop": round(f["stop"], f["precision"]),
                    "target": round(f["target"], f["precision"]),
                    "lots": f["lots"],
                    "risk_usd": round(f["actual_risk"], 2),
                    "strategy": f["strategy"],
                    "cluster": (f.get("clusters") or [None])[0],
                    "quality_rank": f["quality_rank"],
                }
                for f in accepted
            ],
            "suppressed": [
                {"ftmo_symbol": f.get("ftmo_symbol", oanda_to_ftmo(f["pair"])),
                 "reason": f["skip_reason"]}
                for f in suppressed
            ],
        }
        ORDERS_JSON_PATH.write_text(json.dumps(orders_payload, indent=2),
                                    encoding="utf-8")
        print(f"\nOrders template: {ORDERS_JSON_PATH}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate FTMO manual orders from bh_briefing v2 cell fires")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print but do not write bh_briefing_ftmo_orders.json")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
