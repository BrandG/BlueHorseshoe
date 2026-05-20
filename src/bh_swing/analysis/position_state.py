"""Reconcile broker truth with MongoDB bracket metadata.

The cron-fired monitor sees raw IBKR state: a list of open Trade objects, a
list of positions, a list of executions in a recent window. To take a
management action, it needs to know *which* of those orders is the T1
entry, which is the T2 stop, which idea they belong to. That metadata
lives in MongoDB's ``trade_orders`` collection (written by ``PaperTrader``
at submit time).

This module bridges the two: it takes raw broker state + Mongo metadata
and returns ``ManagedPosition`` objects rich enough for ``stop_rules`` to
reason over. Brackets we can't match cleanly (hand-placed in TWS, Mongo
drift, etc.) are flagged unmanaged and the monitor never mutates them.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

logger = logging.getLogger(__name__)

# Order role within a bracket leg's broker_order_ids array
# (set by PaperTrader.place_bracket_order: [entry, tp, stop]).
ROLE_ENTRY = "entry"
ROLE_TAKE_PROFIT = "tp"
ROLE_STOP = "stop"
_ROLES_BY_INDEX = [ROLE_ENTRY, ROLE_TAKE_PROFIT, ROLE_STOP]


@dataclass(frozen=True)
class BrokerOrderView:
    """Lightweight view of a single broker order, leg-role-annotated."""
    order_id: int
    symbol: str
    action: str        # "BUY" | "SELL"
    order_type: str    # "LMT" | "STP" | ...
    limit_price: float
    stop_price: float
    status: str        # "Submitted" | "PreSubmitted" | "Filled" | "Cancelled" | ...
    filled_qty: int
    remaining_qty: int


@dataclass(frozen=True)
class BracketLeg:
    """One half (T1 or T2) of a split bracket as we currently understand it.

    Each leg has three child orders: entry (BUY LMT), take-profit (SELL LMT),
    and stop-loss (SELL STP). All three share a parentId at IBKR; locally
    they share an ``order_ref`` in the Mongo ``trade_orders`` doc.
    """
    leg: str                      # "T1" | "T2"
    quantity: int                 # original bracket quantity
    entry_price: float            # original entry limit from idea
    take_profit_price: float      # original TP price from idea
    stop_loss_price: float        # original stop from idea
    entry_order: Optional[BrokerOrderView] = None
    take_profit_order: Optional[BrokerOrderView] = None
    stop_order: Optional[BrokerOrderView] = None

    @property
    def entry_filled(self) -> bool:
        """True if the entry has fully filled at the broker."""
        if self.entry_order is None:
            return False
        return self.entry_order.status == "Filled"

    @property
    def entry_partially_filled(self) -> bool:
        if self.entry_order is None:
            return False
        return self.entry_order.filled_qty > 0 and not self.entry_filled

    @property
    def stop_is_alive(self) -> bool:
        """Is the stop-loss order still working at the broker?"""
        if self.stop_order is None:
            return False
        return self.stop_order.status in ("Submitted", "PreSubmitted")


@dataclass(frozen=True)
class ManagedPosition:
    """A position the system has full bracket metadata for, and can act on."""
    symbol: str
    idea_id: str
    side: str                    # "long" | "short" — Phase 1 is long-only
    entry_price: float           # original limit price from the trade idea
    target_price: float          # T2 target from idea
    original_stop_price: float   # the stop that was set at submit time
    legs: list[BracketLeg]
    broker_position_qty: int     # signed: positive = long, 0 = flat
    broker_avg_cost: float

    @property
    def t1(self) -> Optional[BracketLeg]:
        return next((l for l in self.legs if l.leg == "T1"), None)

    @property
    def t2(self) -> Optional[BracketLeg]:
        return next((l for l in self.legs if l.leg == "T2"), None)


@dataclass(frozen=True)
class BuildResult:
    """Output of build_managed_positions()."""
    managed: list[ManagedPosition]
    unmanaged_symbols: list[str]   # symbols with broker state we can't match
    drift_notes: list[str]         # short per-issue notes for journaling


def _broker_order_to_view(trade) -> Optional[BrokerOrderView]:
    """Convert an ib_async Trade to a BrokerOrderView, defensively."""
    try:
        order = trade.order
        status = trade.orderStatus
        return BrokerOrderView(
            order_id=int(getattr(order, "orderId", 0) or 0),
            symbol=getattr(trade.contract, "symbol", ""),
            action=getattr(order, "action", "") or "",
            order_type=getattr(order, "orderType", "") or "",
            limit_price=float(getattr(order, "lmtPrice", 0.0) or 0.0),
            stop_price=float(getattr(order, "auxPrice", 0.0) or 0.0),
            status=getattr(status, "status", "") or "",
            filled_qty=int(float(getattr(status, "filled", 0) or 0)),
            remaining_qty=int(float(getattr(status, "remaining", 0) or 0)),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not view broker order: %s", e)
        return None


def _index_views_by_id(open_trades: Iterable) -> dict[int, BrokerOrderView]:
    out: dict[int, BrokerOrderView] = {}
    for t in open_trades:
        v = _broker_order_to_view(t)
        if v is not None and v.order_id:
            out[v.order_id] = v
    return out


def _classify_view_role(
    view: BrokerOrderView, action_for_entry: str
) -> Optional[str]:
    """Disambiguate entry vs TP vs stop using IBKR action+orderType.

    For a long bracket: entry = BUY LMT, TP = SELL LMT, stop = SELL STP.
    For a short bracket: entry = SELL LMT, TP = BUY LMT, stop = BUY STP.
    """
    if view.action == action_for_entry and view.order_type == "LMT":
        return ROLE_ENTRY
    opp = "SELL" if action_for_entry == "BUY" else "BUY"
    if view.action == opp and view.order_type == "LMT":
        return ROLE_TAKE_PROFIT
    if view.action == opp and view.order_type == "STP":
        return ROLE_STOP
    return None


def _assign_legs_to_views(
    mongo_legs: list[Mapping],
    views_by_id: dict[int, BrokerOrderView],
    side: str,
    broker_position_qty: float,
) -> tuple[list[BracketLeg], list[str]]:
    """For each Mongo leg doc, attach the matching broker order views.

    Returns (legs, drift_notes). Drift notes flag issues that don't break
    management (e.g., stop already cancelled) but are worth journaling.

    Inference rule for missing entry orders: IBKR drops filled/cancelled
    orders from reqAllOpenOrders(). If Mongo recorded that we submitted
    entry order X, X is missing from open_trades, AND the broker reports
    we hold the position (broker_position_qty != 0), then X filled — a
    cancelled entry would have left qty=0. We synthesize a Filled view
    so downstream rules (propose_stop_advancement) can act. Without this,
    every position whose entry has actually filled looks like "entry never
    filled" forever.
    """
    action_for_entry = "BUY" if side == "long" else "SELL"
    legs: list[BracketLeg] = []
    drift_notes: list[str] = []
    position_held = broker_position_qty != 0

    for doc in mongo_legs:
        ids = list(doc.get("broker_order_ids") or [])
        leg_name = str(doc.get("leg", ""))
        symbol = str(doc.get("symbol", ""))
        leg_qty = int(doc.get("quantity", 0) or 0)
        leg_limit = float(doc.get("limit_price", 0.0) or 0.0)

        entry_v = tp_v = stop_v = None
        missing_oids: list[int] = []
        for idx, oid in enumerate(ids):
            try:
                oid_int = int(oid)
            except (TypeError, ValueError):
                continue
            v = views_by_id.get(oid_int)
            if v is None:
                # Filled or cancelled (not in open-orders snapshot). Defer
                # to post-loop synthesis when we know which role this was.
                missing_oids.append(oid_int)
                continue
            role = _classify_view_role(v, action_for_entry)
            if role == ROLE_ENTRY:
                entry_v = v
            elif role == ROLE_TAKE_PROFIT:
                tp_v = v
            elif role == ROLE_STOP:
                stop_v = v
            else:
                drift_notes.append(
                    f"{symbol} {leg_name}: order {oid_int} role unrecognized "
                    f"(action={v.action} type={v.order_type})"
                )

        # Entry-fill inference: if the entry order is missing from open
        # orders AND broker still holds the position, the entry filled.
        # Synthesize a Filled view so entry_filled works correctly.
        if entry_v is None and position_held and missing_oids:
            # Convention: entry is the first broker_order_id in Mongo (set
            # at submit time by PaperTrader). Use it for the synthetic id
            # so audit trails line up.
            entry_v = BrokerOrderView(
                order_id=missing_oids[0],
                symbol=symbol,
                action=action_for_entry,
                order_type="LMT",
                limit_price=leg_limit,
                stop_price=0.0,
                status="Filled",
                filled_qty=leg_qty,
                remaining_qty=0,
            )

        legs.append(BracketLeg(
            leg=leg_name,
            quantity=leg_qty,
            entry_price=leg_limit,
            take_profit_price=float(doc.get("take_profit_price", 0.0) or 0.0),
            stop_loss_price=float(doc.get("stop_loss_price", 0.0) or 0.0),
            entry_order=entry_v,
            take_profit_order=tp_v,
            stop_order=stop_v,
        ))
    return legs, drift_notes


def build_managed_positions(
    broker_positions: Iterable[Mapping],
    broker_open_trades: Iterable,
    trade_orders_collection,
) -> BuildResult:
    """Merge broker truth with Mongo bracket metadata.

    Args:
        broker_positions: list of dicts from ``IBKRClient.get_positions()``.
        broker_open_trades: list of ``ib_async.Trade`` objects from
            ``IBKRClient.get_open_trades()``.
        trade_orders_collection: MongoDB collection or None. If None, every
            position is reported as unmanaged.

    Returns:
        BuildResult with managed positions, unmanaged symbols, and drift notes.
    """
    views_by_id = _index_views_by_id(broker_open_trades)
    managed: list[ManagedPosition] = []
    unmanaged: list[str] = []
    drift: list[str] = []

    for pos in broker_positions:
        qty = float(pos.get("position", 0) or 0)
        if qty == 0:
            continue
        symbol = str(pos.get("symbol", ""))
        side = "long" if qty > 0 else "short"

        if trade_orders_collection is None:
            unmanaged.append(symbol)
            drift.append(f"{symbol}: no Mongo trade_orders available")
            continue

        # Find this symbol's most recently submitted bracket (T1+T2 share idea_id).
        try:
            cursor = trade_orders_collection.find(
                {"symbol": symbol, "status": "submitted"}
            ).sort("submitted_at", -1)
            docs = list(cursor)
        except Exception as e:  # noqa: BLE001
            drift.append(f"{symbol}: Mongo lookup failed: {e}")
            unmanaged.append(symbol)
            continue

        if not docs:
            unmanaged.append(symbol)
            drift.append(f"{symbol}: no trade_orders rows; treating as unmanaged")
            continue

        # Group by idea_id; take the newest (highest submitted_at).
        groups: dict[str, list[Mapping]] = {}
        for doc in docs:
            groups.setdefault(str(doc.get("idea_id", "")), []).append(doc)
        if not groups:
            unmanaged.append(symbol)
            continue
        idea_id, mongo_legs = max(
            groups.items(),
            key=lambda kv: max(d.get("submitted_at") or 0 for d in kv[1]),
        )

        # Original bracket-wide attributes come from the first leg row.
        first = mongo_legs[0]
        entry_price = float(first.get("limit_price", 0.0) or 0.0)
        target_price = float(
            next(
                (d.get("take_profit_price") for d in mongo_legs if d.get("leg") == "T2"),
                first.get("take_profit_price", 0.0),
            ) or 0.0
        )
        original_stop = float(first.get("stop_loss_price", 0.0) or 0.0)

        legs, leg_drift = _assign_legs_to_views(mongo_legs, views_by_id, side, qty)
        drift.extend(leg_drift)

        managed.append(ManagedPosition(
            symbol=symbol,
            idea_id=idea_id,
            side=side,
            entry_price=entry_price,
            target_price=target_price,
            original_stop_price=original_stop,
            legs=legs,
            broker_position_qty=int(qty),
            broker_avg_cost=float(pos.get("avg_cost", 0.0) or 0.0),
        ))

    return BuildResult(managed=managed, unmanaged_symbols=unmanaged, drift_notes=drift)
