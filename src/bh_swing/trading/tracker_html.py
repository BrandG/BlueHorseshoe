"""Render src/graphs/swing_tracker.html — the human-readable position view.

Single static page, regenerated every monitor tick. No JS framework, no live
poll: the page is a snapshot of the moment the monitor last ran. The file
mtime tells you how fresh it is.
"""
from __future__ import annotations

import html
import logging
import os
from datetime import datetime, timezone
from typing import Iterable, Mapping

from bluehorseshoe.core.config import REPO_ROOT

logger = logging.getLogger(__name__)

TRACKER_PATH = os.path.join(REPO_ROOT, "src", "graphs", "swing_tracker.html")


_CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       background: #f7f7f8; color: #222; margin: 0; padding: 24px; }
h1 { font-size: 22px; margin: 0 0 4px 0; }
h2 { font-size: 16px; margin: 24px 0 8px 0; color: #555;
     text-transform: uppercase; letter-spacing: 0.5px; }
.meta { color: #888; font-size: 12px; margin-bottom: 24px; }
.cards { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 16px; }
.card { background: white; border-radius: 8px; padding: 14px 18px;
        box-shadow: 0 1px 2px rgba(0,0,0,0.05); min-width: 160px; }
.card .label { font-size: 11px; color: #999; text-transform: uppercase;
               letter-spacing: 0.5px; }
.card .value { font-size: 20px; font-weight: 600; margin-top: 4px;
               font-variant-numeric: tabular-nums; }
table { width: 100%; border-collapse: collapse; background: white;
        border-radius: 8px; overflow: hidden;
        box-shadow: 0 1px 2px rgba(0,0,0,0.05); }
th { background: #fafafa; color: #666; text-align: left; padding: 10px 12px;
     font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px;
     border-bottom: 1px solid #eee; }
td { padding: 10px 12px; border-bottom: 1px solid #f3f3f3; font-size: 13px;
     font-variant-numeric: tabular-nums; }
tr:last-child td { border-bottom: none; }
.empty { color: #aaa; font-style: italic; padding: 12px; }
.event { color: #888; font-size: 11px; }
.event-fill_detected { color: #2563eb; }
.event-position_opened { color: #16a34a; }
.event-position_closed { color: #6b7280; }
.event-order_placed { color: #16a34a; }
.event-order_rejected { color: #dc2626; }
.event-run_error { color: #dc2626; }
.event-skip_paused { color: #d97706; }
.num { text-align: right; }
"""


def _fmt_money(v: float) -> str:
    return f"${v:,.2f}"


def _fmt_int(v) -> str:
    try:
        return f"{int(v):,}"
    except (TypeError, ValueError):
        return str(v)


def _trade_row(trade) -> dict:
    """Extract render-safe fields from an ib_async Trade object."""
    try:
        return {
            "symbol": getattr(trade.contract, "symbol", ""),
            "action": getattr(trade.order, "action", ""),
            "qty": getattr(trade.order, "totalQuantity", 0),
            "order_type": getattr(trade.order, "orderType", ""),
            "limit_price": getattr(trade.order, "lmtPrice", 0.0) or 0.0,
            "stop_price": getattr(trade.order, "auxPrice", 0.0) or 0.0,
            "tif": getattr(trade.order, "tif", ""),
            "status": getattr(trade.orderStatus, "status", ""),
            "filled": getattr(trade.orderStatus, "filled", 0),
            "order_id": getattr(trade.order, "orderId", ""),
            "parent_id": getattr(trade.order, "parentId", 0),
        }
    except Exception as e:  # noqa: BLE001 — best-effort renderer
        logger.warning("Failed to render trade: %s", e)
        return {"symbol": "?", "status": f"render_error: {e}"}


def render(
    account: Mapping[str, float],
    positions: Iterable[Mapping],
    open_trades: Iterable,
    recent_events: Iterable[Mapping[str, str]],
    *,
    output_path: str = TRACKER_PATH,
) -> str:
    """Write the tracker HTML and return the path."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    cards = []
    for label, key in (
        ("Net Liquidation", "net_liquidation"),
        ("Settled Cash", "settled_cash"),
        ("Available Funds", "available_funds"),
        ("Buying Power", "buying_power"),
    ):
        cards.append(
            f'<div class="card"><div class="label">{html.escape(label)}</div>'
            f'<div class="value">{_fmt_money(float(account.get(key, 0.0) or 0.0))}</div></div>'
        )
    account_id = html.escape(str(account.get("account_id", "")))

    pos_list = list(positions)
    if pos_list:
        pos_rows = []
        for p in pos_list:
            qty = float(p.get("position", 0) or 0)
            if qty == 0:
                continue  # IBKR sometimes returns flat positions; skip them
            pos_rows.append(
                "<tr>"
                f"<td>{html.escape(str(p.get('symbol', '')))}</td>"
                f"<td class=num>{_fmt_int(qty)}</td>"
                f"<td class=num>{_fmt_money(float(p.get('avg_cost', 0.0) or 0.0))}</td>"
                f"<td>{html.escape(str(p.get('contract_type', '')))}</td>"
                f"<td>{html.escape(str(p.get('currency', '')))}</td>"
                "</tr>"
            )
        positions_table = (
            "<table><tr><th>Symbol</th><th class=num>Qty</th>"
            "<th class=num>Avg Cost</th><th>Type</th><th>Ccy</th></tr>"
            + "".join(pos_rows) + "</table>"
        ) if pos_rows else '<div class="empty">No open positions.</div>'
    else:
        positions_table = '<div class="empty">No open positions.</div>'

    trade_rows = [_trade_row(t) for t in open_trades]
    if trade_rows:
        order_rows_html = []
        for t in trade_rows:
            price_cell = (
                _fmt_money(t["limit_price"]) if t["limit_price"]
                else (_fmt_money(t["stop_price"]) if t["stop_price"] else "—")
            )
            order_rows_html.append(
                "<tr>"
                f"<td>{html.escape(str(t.get('symbol', '')))}</td>"
                f"<td>{html.escape(str(t.get('action', '')))}</td>"
                f"<td class=num>{_fmt_int(t.get('qty', 0))}</td>"
                f"<td>{html.escape(str(t.get('order_type', '')))}</td>"
                f"<td class=num>{price_cell}</td>"
                f"<td>{html.escape(str(t.get('tif', '')))}</td>"
                f"<td>{html.escape(str(t.get('status', '')))}</td>"
                f"<td class=num>{_fmt_int(t.get('filled', 0))}</td>"
                f"<td class=num>{html.escape(str(t.get('order_id', '')))}</td>"
                "</tr>"
            )
        orders_table = (
            "<table><tr><th>Symbol</th><th>Action</th><th class=num>Qty</th>"
            "<th>Type</th><th class=num>Price</th><th>TIF</th>"
            "<th>Status</th><th class=num>Filled</th><th class=num>OrderId</th></tr>"
            + "".join(order_rows_html) + "</table>"
        )
    else:
        orders_table = '<div class="empty">No working orders.</div>'

    event_rows_html = []
    for r in recent_events:
        ev = r.get("event", "")
        event_rows_html.append(
            "<tr>"
            f"<td class=event>{html.escape(r.get('ts_utc', ''))}</td>"
            f"<td class='event event-{html.escape(ev)}'>{html.escape(ev)}</td>"
            f"<td>{html.escape(r.get('symbol', ''))}</td>"
            f"<td>{html.escape(r.get('side', ''))}</td>"
            f"<td class=num>{html.escape(r.get('quantity', ''))}</td>"
            f"<td class=num>{html.escape(r.get('price', ''))}</td>"
            f"<td>{html.escape(r.get('note', ''))}</td>"
            "</tr>"
        )
    events_table = (
        "<table><tr><th>Time (UTC)</th><th>Event</th><th>Symbol</th>"
        "<th>Side</th><th class=num>Qty</th><th class=num>Price</th><th>Note</th></tr>"
        + "".join(event_rows_html) + "</table>"
    ) if event_rows_html else '<div class="empty">No journal events yet.</div>'

    html_out = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>BH Swing Tracker</title>
<style>{_CSS}</style>
</head>
<body>
<h1>BH Swing Tracker</h1>
<div class="meta">Account {account_id} &middot; Rendered {now}</div>
<div class="cards">{''.join(cards)}</div>
<h2>Open Positions</h2>
{positions_table}
<h2>Working Orders</h2>
{orders_table}
<h2>Recent Journal Events</h2>
{events_table}
</body></html>
"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_out)
    return output_path
