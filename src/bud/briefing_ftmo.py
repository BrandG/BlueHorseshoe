"""BH Briefing → FTMO live-order generator.

Wraps bud.briefing.evaluate_fires() to produce manually-placeable FTMO orders:
maps OANDA pairs to FTMO .sim symbols, computes lot sizing per the v2_paper
risk profile (0.5% × $10K = $50/R, max 5 concurrent), applies cluster
suppression from bud/config.json, and reads bud/positions.json to skip
pairs already open on the live challenge.

Account, risk, instruments, and clusters live in the shared FTMO trade
envelope (bud/config.json + bud/envelope.py), kept consistent across the
H4 cron channel (this tool) and any human-driven order placement. Risk per
trade and concurrency cap are overridden to match v2_paper.

Two cadences:
  - every H4 close (cron, runs after bud.briefing)
  - once-daily summary at 22:30 UTC weekday

Output:
  - Console table: # | FTMO Symbol | Cluster | Cell | Entry | Stop | Target | Lots | Risk$ | Rank
  - JSON file (src/bh_briefing_ftmo_orders.json) for clipboard/copy use
  - Position-aware: skips fires on pairs already in src/bud/positions.json
  - Cluster-aware: suppresses fires whose cluster is occupied by an open
    position OR by an earlier (higher-ranked) fire in the same run
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

from bh_ftmo.data.fx_store import FxStore

from bud.briefing import (
    CELLS, CELL_QUALITY_RANK, TP_PCT, STOP_PCT,
    evaluate_fires, _send_html_email,
)
from bud.diagnostics import (
    FunnelTrace, render_funnel_trace,
    record_fire_event, read_liveness, render_liveness,
)
from bud.envelope import (
    DEFAULT_CONFIG_PATH, DEFAULT_POSITIONS_PATH,
    PositionsUnreadable, load_config, load_positions_strict,
    symbol_to_clusters_map,
)

REPO_ROOT = Path(__file__).resolve().parents[2]  # src/bud/<this> -> repo root
ORDERS_JSON_PATH = REPO_ROOT / "src" / "bh_briefing_ftmo_orders.json"
BRIEFING_DIR = REPO_ROOT / "src" / "logs" / "briefings_ftmo"

# Overrides applied on top of bud/config.json — matches v2_paper risk envelope
RISK_PER_TRADE_PCT = 0.005    # 0.5% (envelope default is 1%)
MAX_CONCURRENT_POSITIONS = 5   # matches v2_paper (envelope default is 3)
MAX_DAILY_RISK_PCT = 0.04      # unchanged from envelope

LOG = logging.getLogger("bh_briefing.ftmo")


def oanda_to_ftmo(pair: str) -> str:
    """USD_JPY -> USDJPY.sim. FTMO platform convention."""
    return pair.replace("_", "") + ".sim"


def ftmo_to_oanda(sym: str) -> str:
    """USDJPY.sim -> USD_JPY. Inverse of oanda_to_ftmo for 6-char FX symbols."""
    base = sym.replace(".sim", "")
    return f"{base[:3]}_{base[3:]}" if len(base) == 6 else base


def _latest_mid_close(store: FxStore, pair: str) -> Optional[float]:
    """Most-recent closed H4 mid close for a pair, or None if unavailable."""
    try:
        df = store.load(pair, granularity="H4", include_incomplete=False)
    except Exception:  # noqa: BLE001 — any load failure means "no price"
        return None
    if df is None or df.empty:
        return None
    last = df.iloc[-1]
    return float((last["close_bid"] + last["close_ask"]) / 2.0)


def _assess_position(
    p: dict,
    current: Optional[float],
    inst: Optional[dict],
    fire_dirs: set[str],
) -> dict:
    """Pure health assessment for one position (no I/O).

    ``current`` = latest H4 mid close (or None if unavailable). ``fire_dirs`` =
    the set of directions currently firing on this pair. Returns a health dict
    with unrealized P&L (pips + $), remaining room to stop as a fraction of the
    original entry->stop distance (>1 = in profit, 0 = at stop, <=0 = breached),
    a signal verdict, and a single status flag.
    """
    pos_dir = "long" if str(p.get("side", "buy")).lower() == "buy" else "short"
    entry = float(p.get("entry", 0.0) or 0.0)
    stop = float(p.get("stop", 0.0) or 0.0)
    lots = float(p.get("lots", 0.0) or 0.0)
    health: dict[str, Any] = {
        "ftmo_symbol": p.get("ftmo_symbol", ""), "side": p.get("side", ""),
        "pos_dir": pos_dir, "current": current,
    }
    if current is None or inst is None or entry <= 0 or stop <= 0:
        health.update(status="NO DATA", signal="?",
                      reason="no H4 price / instrument config")
        return health

    pip = float(inst["pip_size"])
    dpp = float(inst["dollar_per_pip_per_lot"])
    sign = 1.0 if pos_dir == "long" else -1.0
    pnl_pips = sign * (current - entry) / pip
    pnl_usd = pnl_pips * dpp * lots
    stop_total = abs(entry - stop) / pip
    room_pips = sign * (current - stop) / pip            # >0 room, <=0 breached
    room_frac = room_pips / stop_total if stop_total > 0 else 0.0

    opp = "short" if pos_dir == "long" else "long"
    if opp in fire_dirs:
        signal = "FLIPPED"
    elif pos_dir in fire_dirs:
        signal = "supports"
    else:
        signal = "none"

    if room_frac <= 0:
        status = "AT/PAST STOP"
    elif signal == "FLIPPED":
        # CRITICAL = get out now. Replaces the retired score-degradation check:
        # the cell quality rank is static and can't decay, so the only live
        # "thesis broke" signal is an opposite-direction fire (FLIPPED).
        # Outranks NEAR STOP — a thesis inversion is more actionable than price
        # drifting toward a stop the broker will honor automatically. Note: a
        # held swing position almost never still fires its H4 entry, so
        # signal=="none" is the steady state and must NOT imply CRITICAL — an
        # underwater-but-no-flip position drops through to NEAR STOP/UNDERWATER.
        status = "CRITICAL"
    elif room_frac <= 0.25:
        status = "NEAR STOP"
    elif pnl_usd < 0:
        status = "UNDERWATER"
    else:
        status = "OK"

    health.update(
        pnl_usd=pnl_usd, pnl_pips=pnl_pips, room_pips=room_pips,
        room_frac=room_frac, signal=signal, status=status,
        reason=(f"P&L {pnl_usd:+,.0f} ({pnl_pips:+.0f}p), "
                f"{room_frac * 100:.0f}% room to stop, signal: {signal}"),
    )
    return health


def compute_position_health(
    positions: list[dict],
    fires_raw: list[dict],
    instrument_map: dict[str, dict],
) -> list[dict]:
    """Assess each open position against the latest H4 bar (loads live prices).

    ``fires_raw`` must be the *unfiltered* fire list (before position-skip), so
    signals on already-held pairs are still visible. Delegates the per-position
    decision to the pure :func:`_assess_position`.
    """
    if not positions:
        return []

    fires_by_pair: dict[str, set[str]] = {}
    for f in fires_raw:
        fires_by_pair.setdefault(f["pair"], set()).add(f["direction"])

    out: list[dict] = []
    store = FxStore(read_only=True)
    try:
        for p in positions:
            sym = p["ftmo_symbol"]
            pair = ftmo_to_oanda(sym)
            current = _latest_mid_close(store, pair)
            out.append(_assess_position(
                p, current, instrument_map.get(sym), fires_by_pair.get(pair, set())))
    finally:
        store.close()
    return out


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
                   now_utc: datetime,
                   health: Optional[list[dict]] = None,
                   positions_warning: Optional[str] = None) -> str:
    lines = []
    lines.append(f"BH Briefing → FTMO  ({now_utc.strftime('%Y-%m-%d %H:%M UTC')})")
    if positions_warning:
        lines.append("")
        lines.append(f"⚠ POSITION DATA UNAVAILABLE — {positions_warning}")
        lines.append("  Open positions / health below may be incomplete; do not "
                     "trust this run's position view.")
    lines.append(f"Account: ${account_size:,.0f}  risk/trade: {RISK_PER_TRADE_PCT*100:.2f}%"
                 f"  max concurrent: {MAX_CONCURRENT_POSITIONS}"
                 f"  daily risk: ${daily_risk_used:,.2f} / ${daily_risk_cap:,.2f}")
    if positions:
        lines.append("")
        lines.append("Open positions (read from src/bud/positions.json):")
        for p in positions:
            lines.append(f"  {p['ftmo_symbol']:<14} {p['side']:<5} "
                         f"{p['lots']:>5} lots  entry {p['entry']:<9}  "
                         f"stop {p['stop']:<9}  risk ${p.get('risk_usd', 0):>6.2f}  "
                         f"opened {p.get('opened', '?')}")
    if health:
        lines.append("")
        lines.append("== POSITION HEALTH ==")
        lines.append(f"  {'FTMO Symbol':<14}  {'SIDE':<5}  {'Status':<12}  Detail")
        for h in health:
            side = "BUY" if h["pos_dir"] == "long" else "SELL"
            lines.append(f"  {h['ftmo_symbol']:<14}  {side:<5}  "
                         f"{h['status']:<12}  {h.get('reason', '')}")
    lines.append("")
    if not annotated:
        lines.append("No tradeable fires on this bar (after position + cluster filters).")
    else:
        lines.append("== ORDERS TO PLACE ==")
        lines.append(f"  {'#':>2}  {'FTMO Symbol':<14}  {'SIDE':<6}  "
                     f"{'Cluster':<16}  {'Cell':<18}  {'Trend':<16}  "
                     f"{'Entry':>10}  {'Stop':>10}  {'Target':>10}  "
                     f"{'SL pips':>8}  {'TP pips':>8}  "
                     f"{'Lots':>6}  {'Risk $':>8}  {'Rank':>7}")
        for i, f in enumerate(annotated, 1):
            side = "BUY" if f["direction"] == "long" else "SELL"
            cell_desc = f"{f['strategy']}/{f['entry_mode']} · {f.get('session', '?')}"
            trend = f.get("d1_align", "flat") + (" ⚠" if f.get("ct_warn") else "")
            cluster = (f.get("clusters") or [""])[0] or "—"
            precision = f["precision"]
            ent = f"{f['entry']:.{precision}f}"
            stp = f"{f['stop']:.{precision}f}"
            tgt = f"{f['target']:.{precision}f}"
            pip_size = float(f["instrument"]["pip_size"])
            sl_pips = abs(f["entry"] - f["stop"]) / pip_size
            tp_pips = abs(f["target"] - f["entry"]) / pip_size

            # Sanity check: geometry must match declared side.
            warn = ""
            if side == "BUY":
                if not (f["target"] > f["entry"] > f["stop"]):
                    warn = "  !! GEOMETRY MISMATCH — review before placing"
            else:  # SELL
                if not (f["target"] < f["entry"] < f["stop"]):
                    warn = "  !! GEOMETRY MISMATCH — review before placing"

            lines.append(f"  {i:>2}  {f['ftmo_symbol']:<14}  {side:<6}  "
                         f"{cluster:<16}  {cell_desc:<18}  {trend:<16}  "
                         f"{ent:>10}  {stp:>10}  {tgt:>10}  "
                         f"{sl_pips:>8.1f}  {tp_pips:>8.1f}  "
                         f"{f['lots']:>6.2f}  ${f['actual_risk']:>6.2f}  "
                         f"{f['quality_rank']:>+6.3f}{warn}")
        lines.append("")
        lines.append("  SIDE column: BUY = long (target > entry > stop),  "
                     "SELL = short (target < entry < stop)")
        lines.append(f"  Stop/target are FIXED % offsets from entry "
                     f"(stop {STOP_PCT*100:.1f}% / target {TP_PCT*100:.1f}%). "
                     f"If you fill late at a different price, re-anchor: apply the "
                     f"same %s to your actual fill (SL/TP pips barely change).")
        lines.append("  'limit' cells: place the limit; it's good for the next "
                     "4h bar. 'mid' cells: enter at market, then set stop/target "
                     "off your fill. Don't chase a 'mid' that's already near target.")
    if suppressed:
        lines.append("")
        lines.append("== SUPPRESSED (sized for reference — NOT auto-placed) ==")
        lines.append(f"  {'FTMO Symbol':<14}  {'SIDE':<5}  {'Cell':<18}  "
                     f"{'Entry':>10}  {'Stop':>10}  {'Target':>10}  "
                     f"{'SL pips':>8}  {'TP pips':>8}  {'Lots':>6}  {'Risk $':>8}  Why")
        for f in suppressed:
            side = "BUY" if f["direction"] == "long" else "SELL"
            cell_desc = f"{f['strategy']}/{f.get('entry_mode', '?')} · {f.get('session', '?')}"
            precision = f["precision"]
            pip_size = float(f["instrument"]["pip_size"])
            ent = f"{f['entry']:.{precision}f}"
            stp = f"{f['stop']:.{precision}f}"
            tgt = f"{f['target']:.{precision}f}"
            sl_pips = abs(f["entry"] - f["stop"]) / pip_size
            tp_pips = abs(f["target"] - f["entry"]) / pip_size
            lines.append(f"  {f.get('ftmo_symbol', f['pair']):<14}  {side:<5}  "
                         f"{cell_desc:<18}  {ent:>10}  {stp:>10}  {tgt:>10}  "
                         f"{sl_pips:>8.1f}  {tp_pips:>8.1f}  "
                         f"{f.get('lots', 0):>6.2f}  ${f.get('actual_risk', 0):>6.2f}  "
                         f"{f['skip_reason']}")
    return "\n".join(lines)


_STATUS_COLOR = {
    "OK": "#1a7f37", "UNDERWATER": "#9a6700", "FLIPPED": "#9a6700",
    "CRITICAL": "#cf222e", "NEAR STOP": "#b35900",
    "AT/PAST STOP": "#cf222e", "NO DATA": "#888",
}


def _pnl_color(v: float) -> str:
    """Green for positive, red for negative, grey for flat."""
    if v > 0:
        return "#1a7f37"
    if v < 0:
        return "#cf222e"
    return "#57606a"


def _badge(text: str, color: str) -> str:
    """A rounded, filled status pill (Gmail-safe inline styles)."""
    return (f'<span style="display:inline-block; padding:1px 8px; border-radius:10px; '
            f'background:{color}; color:#fff; font-size:11px; font-weight:600; '
            f'white-space:nowrap;">{html.escape(text)}</span>')


def _summary_cards(cards: list[tuple[str, str]]) -> str:
    """A horizontal strip of label/value KPI cards (table-based for email)."""
    cells = "".join(
        f'<td style="padding:6px 20px 6px 0; vertical-align:top; white-space:nowrap;">'
        f'<div style="font-size:11px; color:#8c959f; text-transform:uppercase; '
        f'letter-spacing:.04em;">{label}</div>'
        f'<div style="font-size:18px; font-weight:600; margin-top:2px;">{value}</div>'
        f'</td>'
        for label, value in cards
    )
    return ('<table style="border-collapse:collapse; margin:12px 0 4px;"><tr>'
            + cells + '</tr></table>')


def _positions_records(annotated: list[dict], now_utc: datetime) -> list[dict]:
    """Recast accepted orders into ``src/bud/positions.json`` shape for copy-paste.

    Uses the *suggested* entry (re-anchor manually if you fill elsewhere). Maps
    the v2 cell fields onto the positions schema: ``strategy/entry_mode`` ->
    ``entry_strategy``, ``quality_rank`` -> ``entry_score``, run date -> ``opened``.
    """
    opened = now_utc.strftime("%Y-%m-%d")
    records = []
    for f in annotated:
        prec = f["precision"]
        records.append({
            "ftmo_symbol": f["ftmo_symbol"],
            "name": f["instrument"].get("name", f["ftmo_symbol"]),
            "side": "buy" if f["direction"] == "long" else "sell",
            "entry": round(f["entry"], prec),
            "stop": round(f["stop"], prec),
            "target": round(f["target"], prec),
            "lots": f["lots"],
            "risk_usd": round(f["actual_risk"], 2),
            "entry_score": round(float(f.get("quality_rank", 0.0)), 4),
            "entry_strategy": f'{f["strategy"]}/{f["entry_mode"]}',
            "opened": opened,
        })
    return records


def render_html(annotated: list[dict], suppressed: list[dict],
                positions: list[dict], account_size: float,
                daily_risk_used: float, daily_risk_cap: float,
                now_utc: datetime,
                health: Optional[list[dict]] = None,
                positions_warning: Optional[str] = None,
                liveness_line: Optional[str] = None) -> str:
    """HTML email body: portfolio summary + position health + sized orders + suppressed."""
    esc = html.escape
    th = "text-align:left; border-bottom:2px solid #d0d7de; padding:5px 8px; font-size:12px; color:#57606a;"
    thr = th + " text-align:right;"
    td = "padding:5px 8px; border-bottom:1px solid #eaeef2;"
    tdr = td + " text-align:right; font-variant-numeric:tabular-nums;"
    zebra = "#f6f8fa"
    health = health or []
    p: list[str] = []
    p.append('<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif; '
             'max-width:820px; color:#1f2328;">')
    p.append('<h1 style="font-size:20px; margin:0 0 2px;">BH Briefing → FTMO</h1>')
    p.append(f'<p style="color:#57606a; font-size:13px; margin:2px 0 0;">'
             f'{esc(now_utc.strftime("%Y-%m-%d %H:%M UTC"))} &nbsp;·&nbsp; '
             f'risk/trade {RISK_PER_TRADE_PCT*100:.2f}% &nbsp;·&nbsp; '
             f'stop {STOP_PCT*100:.1f}% / target {TP_PCT*100:.1f}%</p>')

    # --- Fire-rate liveness ---
    # Makes "0 orders" self-auditing in the email itself: a healthy fire rate +
    # recent last-fire means a quiet bar, not a dead evaluator. See diagnostics.
    if liveness_line:
        p.append(f'<p style="color:#57606a; font-size:12px; margin:6px 0 0; '
                 f'font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;">'
                 f'{esc(liveness_line)}</p>')

    # --- Position-data warning banner ---
    # When positions.json couldn't be read, the summary/health below reflect an
    # empty position set that may be wrong — say so loudly rather than imply flat.
    if positions_warning:
        p.append(
            '<div style="margin:12px 0 0; padding:10px 12px; border-radius:6px; '
            'background:#fff1e5; border:1px solid #e0863a; color:#8a4b14; '
            'font-size:13px;">'
            '<strong>⚠ Position data unavailable.</strong> '
            f'{esc(positions_warning)}<br>'
            'Open positions and health below may be incomplete — do not trust '
            "this run's position view; re-run the briefing once the file is fixed."
            '</div>')

    # --- Portfolio summary ---
    total_unreal = sum(float(h.get("pnl_usd", 0.0) or 0.0) for h in health)
    longs = sum(1 for pp in positions if str(pp.get("side", "")).lower() == "buy")
    shorts = len(positions) - longs
    new_risk = sum(float(f.get("actual_risk", 0.0) or 0.0) for f in annotated)
    risk_pct = (daily_risk_used / daily_risk_cap * 100) if daily_risk_cap else 0.0
    note = ' font-size:12px; color:#8c959f; font-weight:400;'
    p.append(_summary_cards([
        ("Account", f'${account_size:,.0f}'),
        ("Open / max", f'{len(positions)} / {MAX_CONCURRENT_POSITIONS}'),
        ("Unrealized P&amp;L",
         f'<span style="color:{_pnl_color(total_unreal)};">${total_unreal:+,.0f}</span>'),
        ("Net dir", f'{longs}L / {shorts}S'),
        ("Risk on book",
         f'${daily_risk_used:,.0f} <span style="{note}">/ ${daily_risk_cap:,.0f} ({risk_pct:.0f}%)</span>'),
        ("New orders",
         f'{len(annotated)} <span style="{note}">(${new_risk:,.0f})</span>'),
    ]))

    if health:
        p.append('<h2 style="font-size:15px; margin:16px 0 6px;">Position health</h2>')
        p.append('<table style="border-collapse:collapse; width:100%; font-size:13px;"><tr>'
                 f'<th style="{th}">Symbol</th><th style="{th}">Side</th>'
                 f'<th style="{th}">Status</th><th style="{thr}">P&amp;L $</th>'
                 f'<th style="{thr}">P&amp;L pips</th><th style="{thr}">Room to stop</th>'
                 f'<th style="{th}">Signal</th></tr>')
        for i, h in enumerate(health):
            bg = f' background:{zebra};' if i % 2 else ''
            side = "BUY" if h["pos_dir"] == "long" else "SELL"
            side_color = "#1a7f37" if side == "BUY" else "#cf222e"
            status = h.get("status", "?")
            badge = _badge(status, _STATUS_COLOR.get(status, "#57606a"))
            if "pnl_usd" in h:
                pnl_usd = float(h["pnl_usd"])
                pnl_pips = float(h["pnl_pips"])
                room = float(h.get("room_frac", 0.0)) * 100
                room_color = "#cf222e" if room <= 25 else "#1f2328"
                pnl_usd_c = f'<span style="color:{_pnl_color(pnl_usd)};">${pnl_usd:+,.0f}</span>'
                pnl_pips_c = f'<span style="color:{_pnl_color(pnl_pips)};">{pnl_pips:+,.0f}</span>'
                room_c = f'<span style="color:{room_color};">{room:.0f}%</span>'
            else:
                pnl_usd_c = pnl_pips_c = room_c = '<span style="color:#aaa;">—</span>'
            signal = h.get("signal", "")
            sig_color = ("#cf222e" if signal == "FLIPPED"
                         else "#1a7f37" if signal == "supports" else "#8c959f")
            p.append(
                f'<tr style="{bg}"><td style="{td}">{esc(h["ftmo_symbol"])}</td>'
                f'<td style="{td} color:{side_color}; font-weight:600;">{side}</td>'
                f'<td style="{td}">{badge}</td>'
                f'<td style="{tdr}">{pnl_usd_c}</td>'
                f'<td style="{tdr}">{pnl_pips_c}</td>'
                f'<td style="{tdr}">{room_c}</td>'
                f'<td style="{td} color:{sig_color};">{esc(signal)}</td></tr>')
        p.append('</table>')

    p.append('<h2 style="font-size:15px; margin:16px 0 6px;">Orders to place</h2>')
    if not annotated:
        p.append('<p style="color:#57606a; font-size:13px;">No tradeable fires on this bar '
                 '(after position + cluster filters).</p>')
    else:
        left_h = ["#", "Symbol", "SIDE", "Cell", "Trend"]
        right_h = ["Entry", "Stop", "Target", "SL pips", "TP pips", "Lots", "Risk $"]
        header = ("".join(f'<th style="{th}">{c}</th>' for c in left_h)
                  + "".join(f'<th style="{thr}">{c}</th>' for c in right_h))
        p.append(f'<table style="border-collapse:collapse; width:100%; font-size:13px;"><tr>'
                 f'{header}</tr>')
        for i, f in enumerate(annotated, 1):
            bg = f' background:{zebra};' if (i - 1) % 2 else ''
            side = "BUY" if f["direction"] == "long" else "SELL"
            side_color = "#1a7f37" if side == "BUY" else "#cf222e"
            prec = f["precision"]
            pip = float(f["instrument"]["pip_size"])
            sl_pips = abs(f["entry"] - f["stop"]) / pip
            tp_pips = abs(f["target"] - f["entry"]) / pip
            # D1-alignment + session (from evaluate_fires). with-trend carried ~3.3x
            # the per-trade R in the diagnostic; ⚠ marks the negative-counter-trend
            # indicators (atr/candle). See project_briefing_filter_annotations.
            align = f.get("d1_align", "flat")
            align_color = {"with-trend": "#1a7f37",
                           "counter-trend": "#9a6700"}.get(align, "#8c959f")
            trend_txt = align + (" ⚠" if f.get("ct_warn") else "")
            sess = f.get("session", "?")
            left = [
                str(i), esc(f["ftmo_symbol"]),
                f'<b style="color:{side_color};">{side}</b>',
                esc(f'{f["strategy"]}/{f["entry_mode"]} · {sess}'),
                f'<span style="color:{align_color}; font-weight:600;">{esc(trend_txt)}</span>',
            ]
            right = [
                f'{f["entry"]:.{prec}f}', f'{f["stop"]:.{prec}f}', f'{f["target"]:.{prec}f}',
                f'{sl_pips:.1f}', f'{tp_pips:.1f}', f'{f["lots"]:.2f}', f'${f["actual_risk"]:.2f}',
            ]
            row = ("".join(f'<td style="{td}">{c}</td>' for c in left)
                   + "".join(f'<td style="{tdr}">{c}</td>' for c in right))
            p.append(f'<tr style="{bg}">{row}</tr>')
        p.append('</table>')
        p.append(f'<p style="color:#8c959f; font-size:12px; margin-top:6px;">'
                 f'Stop/target are fixed % offsets (stop {STOP_PCT*100:.1f}% / target {TP_PCT*100:.1f}%); '
                 f'if you fill late, re-anchor to your actual fill (pip distances barely change). '
                 f"'limit' cells are good for the next 4h bar.</p>")

    if suppressed:
        p.append('<h2 style="font-size:15px; margin:16px 0 6px;">Suppressed '
                 '<span style="font-size:12px; font-weight:400; color:#8c959f;">'
                 '(sized for reference — NOT auto-placed)</span></h2>')
        sup_left_h = ["Symbol", "SIDE", "Cell"]
        sup_right_h = ["Entry", "Stop", "Target", "SL pips", "TP pips", "Lots", "Risk $", "Why"]
        sup_header = ("".join(f'<th style="{th}">{c}</th>' for c in sup_left_h)
                      + "".join(f'<th style="{thr}">{c}</th>' for c in sup_right_h))
        p.append(f'<table style="border-collapse:collapse; width:100%; font-size:12px; '
                 f'color:#57606a;"><tr>{sup_header}</tr>')
        for i, f in enumerate(suppressed):
            bg = f' background:{zebra};' if i % 2 else ''
            sym = esc(f.get("ftmo_symbol", oanda_to_ftmo(f["pair"])))
            side = "BUY" if f["direction"] == "long" else "SELL"
            side_color = "#1a7f37" if side == "BUY" else "#cf222e"
            prec = f["precision"]
            pip = float(f["instrument"]["pip_size"])
            sl_pips = abs(f["entry"] - f["stop"]) / pip
            tp_pips = abs(f["target"] - f["entry"]) / pip
            sess = f.get("session", "?")
            left = [
                sym,
                f'<b style="color:{side_color};">{side}</b>',
                esc(f'{f["strategy"]}/{f.get("entry_mode", "?")} · {sess}'),
            ]
            right = [
                f'{f["entry"]:.{prec}f}', f'{f["stop"]:.{prec}f}', f'{f["target"]:.{prec}f}',
                f'{sl_pips:.1f}', f'{tp_pips:.1f}',
                f'{f.get("lots", 0):.2f}', f'${f.get("actual_risk", 0):.2f}',
                esc(f["skip_reason"]),
            ]
            row = ("".join(f'<td style="{td}">{c}</td>' for c in left)
                   + "".join(f'<td style="{tdr}">{c}</td>' for c in right))
            p.append(f'<tr style="{bg}">{row}</tr>')
        p.append('</table>')

    if annotated:
        blob = esc(json.dumps(_positions_records(annotated, now_utc), indent=2))
        p.append('<h2 style="font-size:15px; margin:16px 0 6px;">Copy into '
                 '<code>src/bud/positions.json</code></h2>')
        p.append('<p style="color:#8c959f; font-size:12px; margin:0 0 6px;">'
                 'Accepted orders in positions-file shape (suggested entry). Paste the '
                 'ones you actually filled into the open-positions list; delete the rest.</p>')
        p.append(f'<pre style="background:#f6f8fa; border:1px solid #d0d7de; '
                 f'border-radius:6px; padding:10px 12px; font-size:12px; overflow:auto; '
                 f'white-space:pre; '
                 f'font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;">'
                 f'{blob}</pre>')

    p.append('</div>')
    return "\n".join(p)


def run(*, dry_run: bool = False, email: bool = False,
        email_only_if_activity: bool = False, trace: bool = False) -> int:
    config = load_config(DEFAULT_CONFIG_PATH)
    # Strict read so a corrupt/mid-write positions.json surfaces as a warning
    # instead of a silent position-free briefing (see PositionsUnreadable).
    positions_warning: Optional[str] = None
    try:
        positions = load_positions_strict(DEFAULT_POSITIONS_PATH)
    except PositionsUnreadable as exc:
        positions = []
        positions_warning = str(exc)
        LOG.warning("position data unavailable — briefing has no health section: %s", exc)
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
    fires_raw, ordered_cells, bar_ts_by_pair = evaluate_fires()
    # Health uses the *unfiltered* fires so signals on held pairs stay visible.
    health = compute_position_health(positions, fires_raw, instrument_map)
    fires = annotate_fires(fires_raw, instrument_map)

    fires, pos_skipped = apply_position_skip(fires, positions)
    fires, cluster_suppressed = apply_cluster_filter(fires, clusters, positions)

    # Cap by remaining concurrent slots. `capped` is kept separate from the
    # cluster suppressions so the funnel trace can attribute each drop to the
    # right stage; `suppressed` recombines them for the unchanged render/JSON.
    accepted, capped = [], []
    for f in fires:
        if len(accepted) >= remaining_slots:
            capped.append({
                **f,
                "skip_reason": f"over max concurrent ({MAX_CONCURRENT_POSITIONS})",
            })
            continue
        if remaining_daily <= 0:
            capped.append({
                **f, "skip_reason": "daily risk budget exhausted"})
            continue
        lots, actual_risk = compute_lots(
            f["entry"], f["stop"], risk_per_trade_usd, f["instrument"])
        if lots <= 0:
            capped.append({
                **f, "skip_reason": "computed 0 lots"})
            continue
        accepted.append({**f, "lots": lots, "actual_risk": actual_risk})
        remaining_daily -= actual_risk

    suppressed = pos_skipped + cluster_suppressed + capped
    # Size suppressed fires too, so the briefing surfaces full order details
    # (entry/stop/target/lots/risk) for everything it filtered out. A suppressed
    # fire is then actionable on its own — you don't have to correct a stale
    # positions.json and re-run just to learn what the trade would have been.
    # Sizing is slot-independent (compute_lots needs only the geometry + the
    # standard per-trade risk), so these numbers match what the fire would get
    # if it were accepted. Reference only — these are NOT auto-placed.
    for f in suppressed:
        if "lots" in f:
            continue
        lots, actual_risk = compute_lots(
            f["entry"], f["stop"], risk_per_trade_usd, f["instrument"])
        f["lots"] = lots
        f["actual_risk"] = actual_risk
    now_utc = datetime.now(UTC)

    # --- observability: fire-rate liveness + optional funnel trace ----------
    # Record this bar's raw-fire count so "0 orders" can be judged against the
    # normal rate. Keyed by bar_ts → re-runs on the same bar upsert, not double
    # count. Skipped under --dry-run so probing can't pollute the base rate.
    latest_bar = max(bar_ts_by_pair.values()) if bar_ts_by_pair else None
    if not dry_run and latest_bar is not None:
        record_fire_event(latest_bar, len(ordered_cells), len(fires_raw),
                          len(accepted), now_utc=now_utc)
    liveness = read_liveness(now_utc=now_utc)
    print(render_liveness(liveness))
    if trace:
        all_pairs = {c.pair for c in CELLS}
        loaded = set(bar_ts_by_pair)
        print(render_funnel_trace(FunnelTrace(
            bar_ts=latest_bar, cells_defined=len(ordered_cells),
            pairs_total=len(all_pairs), pairs_loaded=len(loaded),
            starved_pairs=sorted(all_pairs - loaded), fires_raw=fires_raw,
            pos_skipped=pos_skipped, cluster_suppressed=cluster_suppressed,
            capped=capped, accepted=accepted, slots_left=remaining_slots,
            daily_room=remaining_daily)))
    print(render_console(accepted, suppressed, positions, account_size,
                         daily_risk_used, daily_risk_cap, now_utc, health=health,
                         positions_warning=positions_warning))

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
            "position_health": [
                {k: v for k, v in h.items() if k != "pos_dir"} for h in health
            ],
            "orders": [
                {
                    "ftmo_symbol": f["ftmo_symbol"],
                    "side": "buy" if f["direction"] == "long" else "sell",
                    "entry_mode": f["entry_mode"],
                    "entry": round(f["entry"], f["precision"]),
                    "stop": round(f["stop"], f["precision"]),
                    "target": round(f["target"], f["precision"]),
                    "stop_pips": round(abs(f["entry"] - f["stop"]) / float(f["instrument"]["pip_size"]), 1),
                    "target_pips": round(abs(f["target"] - f["entry"]) / float(f["instrument"]["pip_size"]), 1),
                    "stop_pct": round(STOP_PCT * 100, 3),
                    "target_pct": round(TP_PCT * 100, 3),
                    "lots": f["lots"],
                    "risk_usd": round(f["actual_risk"], 2),
                    "strategy": f["strategy"],
                    "cluster": (f.get("clusters") or [None])[0],
                    "quality_rank": f["quality_rank"],
                }
                for f in accepted
            ],
            "suppressed": [
                {
                    "ftmo_symbol": f.get("ftmo_symbol", oanda_to_ftmo(f["pair"])),
                    "side": "buy" if f["direction"] == "long" else "sell",
                    "entry_mode": f.get("entry_mode"),
                    "entry": round(f["entry"], f["precision"]),
                    "stop": round(f["stop"], f["precision"]),
                    "target": round(f["target"], f["precision"]),
                    "stop_pips": round(abs(f["entry"] - f["stop"]) / float(f["instrument"]["pip_size"]), 1),
                    "target_pips": round(abs(f["target"] - f["entry"]) / float(f["instrument"]["pip_size"]), 1),
                    "lots": f.get("lots", 0),
                    "risk_usd": round(f.get("actual_risk", 0), 2),
                    "strategy": f["strategy"],
                    "quality_rank": f.get("quality_rank"),
                    "reason": f["skip_reason"],
                }
                for f in suppressed
            ],
        }
        ORDERS_JSON_PATH.write_text(json.dumps(orders_payload, indent=2),
                                    encoding="utf-8")
        print(f"\nOrders template: {ORDERS_JSON_PATH}")

    if email:
        html_body = render_html(accepted, suppressed, positions, account_size,
                                daily_risk_used, daily_risk_cap, now_utc, health=health,
                                positions_warning=positions_warning,
                                liveness_line=render_liveness(liveness))
        BRIEFING_DIR.mkdir(parents=True, exist_ok=True)
        archive_path = BRIEFING_DIR / f"briefing_ftmo_{now_utc.strftime('%Y-%m-%d_%H%M')}.html"
        archive_path.write_text(html_body, encoding="utf-8")
        LOG.info("archived FTMO briefing → %s", archive_path)
        # "Activity" = something actionable to show: a sized order, an open
        # position to report health on, or a position-data failure worth seeing.
        # Stay quiet only when there's none of those.
        has_activity = bool(accepted) or bool(positions) or bool(positions_warning)
        if email_only_if_activity and not has_activity:
            LOG.info("no orders and no open positions — skipping email")
        else:
            n_orders = len(accepted)
            n_pos = len(positions)
            if positions_warning:
                subject = f"[BH FTMO] ⚠ position data unavailable — {n_orders} order(s)"
            else:
                subject = f"[BH FTMO] {n_orders} order(s), {n_pos} position(s)"
            _send_html_email(subject, html_body)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate FTMO manual orders from bh_briefing v2 cell fires")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print but do not write bh_briefing_ftmo_orders.json")
    parser.add_argument("--email", action="store_true",
                        help="Send the briefing (orders + position health) as HTML email")
    parser.add_argument("--email-only-if-activity", action="store_true",
                        help="With --email, only send when there is a sized order "
                             "or an open position to report on")
    parser.add_argument("--trace", action="store_true",
                        help="Print the per-stage funnel trace (cells → fires → "
                             "filters → orders) so a zero-order bar is auditable")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    return run(dry_run=args.dry_run, email=args.email,
               email_only_if_activity=args.email_only_if_activity,
               trace=args.trace)


if __name__ == "__main__":
    sys.exit(main())
