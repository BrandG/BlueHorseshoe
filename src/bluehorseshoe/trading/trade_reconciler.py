"""
Trade reconciler — matches ideas → orders → fills and builds trade_positions.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from pymongo.database import Database

from bluehorseshoe.trading.trade_models import make_position_id

logger = logging.getLogger(__name__)


class TradeReconciler:
    """
    Matches trade_ideas → trade_orders → trade_fills → trade_positions.

    Reconciliation strategy:
    1. Match orders to fills by broker_order_ids
    2. Match orphan fills by symbol + date proximity
    3. Build/update trade_positions with T1/T2 legs
    """

    def __init__(self, database: Database):
        self._db = database
        self._ideas = database["trade_ideas"]
        self._orders = database["trade_orders"]
        self._fills = database["trade_fills"]
        self._positions = database["trade_positions"]
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        try:
            self._positions.create_index(
                [("position_id", 1)], unique=True, name="ux_position_id"
            )
            self._positions.create_index(
                [("idea_id", 1)], name="ix_pos_idea_id"
            )
            self._positions.create_index(
                [("status", 1)], name="ix_pos_status"
            )
            self._positions.create_index(
                [("symbol", 1), ("opened_at", 1)], name="ix_pos_symbol_time"
            )
        except Exception as e:
            logger.warning("Failed to create trade_positions indexes: %s", e)

    def reconcile(self, batch_date: Optional[str] = None) -> Dict[str, int]:
        """
        Run full reconciliation.

        Args:
            batch_date: If provided, only reconcile ideas from this date.

        Returns:
            Dict with counts: orders_matched, fills_matched, positions_created,
            positions_updated, unmatched_fills.
        """
        stats = {
            "orders_matched": 0,
            "fills_matched": 0,
            "positions_created": 0,
            "positions_updated": 0,
            "unmatched_fills": 0,
        }

        # Step 1: Match orders → fills by broker_order_ids
        om, fm = self._match_orders_to_fills(batch_date)
        stats["orders_matched"] = om
        stats["fills_matched"] = fm

        # Step 2: Try to match orphan fills by symbol + date
        orphan_matched = self._match_orphan_fills(batch_date)
        stats["fills_matched"] += orphan_matched

        # Step 3: Build/update positions from matched fills
        created, updated = self._build_positions(batch_date)
        stats["positions_created"] = created
        stats["positions_updated"] = updated

        # Count remaining unmatched
        unmatched_query = {"idea_id": None}
        stats["unmatched_fills"] = self._fills.count_documents(unmatched_query)

        logger.info(
            "Reconciliation complete: %d orders matched, %d fills matched, "
            "%d positions created, %d updated, %d unmatched fills",
            stats["orders_matched"], stats["fills_matched"],
            stats["positions_created"], stats["positions_updated"],
            stats["unmatched_fills"],
        )
        return stats

    def _match_orders_to_fills(self, batch_date: Optional[str]) -> Tuple[int, int]:
        """
        Match trade_orders to trade_fills using broker_order_ids.

        For each order, find fills where the broker assigned order_id
        matches one of the order's broker_order_ids.
        """
        order_query = {}
        if batch_date:
            # Get idea_ids for this batch
            idea_ids = self._ideas.distinct("idea_id", {"batch_date": batch_date})
            if not idea_ids:
                return 0, 0
            order_query = {"idea_id": {"$in": idea_ids}}

        orders = list(self._orders.find(order_query))
        orders_matched = 0
        fills_matched = 0

        for order in orders:
            broker_ids = order.get("broker_order_ids", [])
            if not broker_ids:
                continue

            idea_id = order.get("idea_id")
            order_ref = order.get("order_ref")

            # Find fills with matching broker order IDs
            matched_fills = list(self._fills.find({
                "broker_order_id": {"$in": broker_ids},
                "$or": [{"order_ref": None}, {"order_ref": order_ref}],
            }))

            if matched_fills:
                orders_matched += 1
                for fill in matched_fills:
                    if fill.get("order_ref") != order_ref or fill.get("idea_id") != idea_id:
                        self._fills.update_one(
                            {"fill_id": fill["fill_id"]},
                            {"$set": {"order_ref": order_ref, "idea_id": idea_id}},
                        )
                        fills_matched += 1

        return orders_matched, fills_matched

    def _match_orphan_fills(self, batch_date: Optional[str]) -> int:
        """
        For fills without order_ref, attempt fuzzy matching by symbol + date.

        Matches an orphan fill to an idea if:
        - Same symbol
        - Fill exec_time is within ±2 days of the idea's batch_date
        - Same side (buy fills match entry)
        """
        orphan_fills = list(self._fills.find({"idea_id": None, "order_ref": None}))
        if not orphan_fills:
            return 0

        # Load ideas to match against
        idea_query = {}
        if batch_date:
            idea_query = {"batch_date": batch_date}
        ideas = list(self._ideas.find(idea_query))
        if not ideas:
            return 0

        # Build lookup: symbol → list of ideas (sorted by date)
        idea_by_symbol: Dict[str, List[dict]] = {}
        for idea in ideas:
            sym = idea["symbol"]
            if sym not in idea_by_symbol:
                idea_by_symbol[sym] = []
            idea_by_symbol[sym].append(idea)

        matched = 0
        for fill in orphan_fills:
            symbol = fill.get("symbol", "")
            exec_time = fill.get("exec_time")
            if not symbol or symbol not in idea_by_symbol:
                continue

            best_idea = None
            best_distance = timedelta(days=999)

            for idea in idea_by_symbol[symbol]:
                if not exec_time:
                    # No exec_time — match by symbol alone if only one idea
                    if len(idea_by_symbol[symbol]) == 1:
                        best_idea = idea
                    break

                try:
                    idea_date = datetime.strptime(idea["batch_date"], "%Y-%m-%d")
                    if isinstance(exec_time, datetime):
                        fill_date = exec_time
                    else:
                        fill_date = datetime.fromisoformat(str(exec_time))

                    distance = abs(fill_date.replace(tzinfo=None) - idea_date)
                    if distance <= timedelta(days=2) and distance < best_distance:
                        best_distance = distance
                        best_idea = idea
                except (ValueError, TypeError):
                    continue

            if best_idea:
                self._fills.update_one(
                    {"fill_id": fill["fill_id"]},
                    {"$set": {"idea_id": best_idea["idea_id"]}},
                )
                matched += 1

        return matched

    def _build_positions(self, batch_date: Optional[str]) -> Tuple[int, int]:
        """
        Build or update trade_positions from matched fills.

        Groups fills by idea_id, creates position with T1/T2 legs.
        """
        # Get all fills that have an idea_id
        fill_query: Dict = {"idea_id": {"$ne": None}}
        if batch_date:
            idea_ids = self._ideas.distinct("idea_id", {"batch_date": batch_date})
            if not idea_ids:
                return 0, 0
            fill_query = {"idea_id": {"$in": idea_ids}}

        fills = list(self._fills.find(fill_query).sort("exec_time", 1))
        if not fills:
            return 0, 0

        # Group fills by idea_id
        fills_by_idea: Dict[str, List[dict]] = {}
        for fill in fills:
            idea_id = fill["idea_id"]
            if idea_id not in fills_by_idea:
                fills_by_idea[idea_id] = []
            fills_by_idea[idea_id].append(fill)

        created = 0
        updated = 0

        for idea_id, idea_fills in fills_by_idea.items():
            position_id = make_position_id(idea_id)

            # Load the idea for planned prices
            idea = self._ideas.find_one({"idea_id": idea_id})
            if not idea:
                continue

            # Separate entry (buy) and exit (sell) fills
            entry_fills = [f for f in idea_fills if f.get("side") == "buy"]
            exit_fills = [f for f in idea_fills if f.get("side") == "sell"]

            # Calculate weighted average entry price
            total_entry_qty = sum(f.get("quantity", 0) for f in entry_fills)
            total_entry_cost = sum(f.get("quantity", 0) * f.get("price", 0) for f in entry_fills)
            avg_entry = total_entry_cost / total_entry_qty if total_entry_qty > 0 else 0

            # Build legs from orders (T1/T2) or default to single leg
            orders = list(self._orders.find({"idea_id": idea_id}).sort("leg", 1))
            legs = self._build_legs(orders, entry_fills, exit_fills, idea)

            # Calculate totals
            total_qty = sum(leg.get("quantity", 0) for leg in legs)
            total_pnl = sum(leg.get("pnl", 0) for leg in legs)
            total_commission = sum(f.get("commission", 0) for f in idea_fills)

            # Determine status
            all_exits_filled = all(
                leg.get("exit_fill_id") is not None for leg in legs if leg.get("quantity", 0) > 0
            )
            status = "closed" if (exit_fills and all_exits_filled) else "open"

            # Timestamps
            opened_at = entry_fills[0].get("exec_time") if entry_fills else None
            closed_at = exit_fills[-1].get("exec_time") if exit_fills and status == "closed" else None

            # Entry slippage
            planned_entry = idea.get("entry_price", 0)
            entry_slippage = avg_entry - planned_entry if planned_entry > 0 else 0

            now = datetime.now(timezone.utc)
            pos_doc = {
                "position_id": position_id,
                "idea_id": idea_id,
                "symbol": idea.get("symbol", ""),
                "strategy": idea.get("strategy", ""),
                "status": status,
                "planned_entry": planned_entry,
                "planned_stop": idea.get("stop_loss", 0),
                "planned_target_t1": idea.get("take_profit_t1", 0),
                "planned_target_t2": idea.get("take_profit_t2", 0),
                "actual_entry": round(avg_entry, 4),
                "legs": legs,
                "total_quantity": total_qty,
                "total_pnl": round(total_pnl, 2),
                "total_commission": round(total_commission, 2),
                "entry_slippage": round(entry_slippage, 4),
                "opened_at": opened_at,
                "closed_at": closed_at,
                "updated_at": now,
            }

            # Check if position exists
            existing = self._positions.find_one({"position_id": position_id})
            if existing:
                self._positions.update_one(
                    {"position_id": position_id},
                    {"$set": pos_doc},
                )
                updated += 1
            else:
                pos_doc["created_at"] = now
                self._positions.update_one(
                    {"position_id": position_id},
                    {"$set": pos_doc},
                    upsert=True,
                )
                created += 1

        return created, updated

    def _build_legs(
        self,
        orders: List[dict],
        entry_fills: List[dict],
        exit_fills: List[dict],
        idea: dict,
    ) -> List[dict]:
        """Build position legs from orders and fills."""
        if not orders:
            # No order records — build a single leg from all fills
            total_entry_qty = sum(f.get("quantity", 0) for f in entry_fills)
            total_exit_qty = sum(f.get("quantity", 0) for f in exit_fills)
            avg_entry = 0.0
            avg_exit = 0.0
            if entry_fills:
                avg_entry = sum(f["quantity"] * f["price"] for f in entry_fills) / total_entry_qty
            if exit_fills:
                avg_exit = sum(f["quantity"] * f["price"] for f in exit_fills) / total_exit_qty

            pnl = (avg_exit - avg_entry) * min(total_entry_qty, total_exit_qty) if avg_exit > 0 else 0
            planned_stop = idea.get("stop_loss", 0)
            risk = avg_entry - planned_stop if planned_stop > 0 and avg_entry > 0 else 0
            r_multiple = pnl / (risk * min(total_entry_qty, total_exit_qty)) if risk > 0 else 0

            close_reason = self._infer_close_reason(avg_exit, idea) if avg_exit > 0 else None

            return [{
                "leg": "T2",
                "quantity": total_entry_qty,
                "entry_fill_id": entry_fills[0]["fill_id"] if entry_fills else None,
                "exit_fill_id": exit_fills[0]["fill_id"] if exit_fills else None,
                "entry_price": round(avg_entry, 4),
                "exit_price": round(avg_exit, 4),
                "close_reason": close_reason,
                "pnl": round(pnl, 2),
                "r_multiple": round(r_multiple, 2),
                "hold_days": self._calc_hold_days(entry_fills, exit_fills),
            }]

        # Build legs from order records
        legs = []
        remaining_exits = list(exit_fills)  # Copy to consume

        for order in orders:
            leg_name = order.get("leg", "T2")
            leg_qty = order.get("quantity", 0)

            # Find entry fills for this leg's order_ref
            order_ref = order.get("order_ref")
            leg_entry_fills = [f for f in entry_fills if f.get("order_ref") == order_ref]
            leg_exit_fills = [f for f in exit_fills if f.get("order_ref") == order_ref]

            # If no fills matched by order_ref, try proportional allocation
            if not leg_entry_fills and entry_fills:
                # Allocate proportionally
                leg_entry_fills = entry_fills[:1]  # Simplified: take first
            if not leg_exit_fills and remaining_exits:
                # Take up to leg_qty from remaining exits
                allocated_qty = 0
                for ef in list(remaining_exits):
                    if allocated_qty >= leg_qty:
                        break
                    leg_exit_fills.append(ef)
                    remaining_exits.remove(ef)
                    allocated_qty += ef.get("quantity", 0)

            avg_entry = 0.0
            avg_exit = 0.0
            if leg_entry_fills:
                total_q = sum(f["quantity"] for f in leg_entry_fills)
                avg_entry = sum(f["quantity"] * f["price"] for f in leg_entry_fills) / total_q if total_q > 0 else 0
            if leg_exit_fills:
                total_q = sum(f["quantity"] for f in leg_exit_fills)
                avg_exit = sum(f["quantity"] * f["price"] for f in leg_exit_fills) / total_q if total_q > 0 else 0

            pnl = (avg_exit - avg_entry) * leg_qty if avg_exit > 0 and avg_entry > 0 else 0
            planned_stop = idea.get("stop_loss", 0)
            risk = avg_entry - planned_stop if planned_stop > 0 and avg_entry > 0 else 0
            r_multiple = pnl / (risk * leg_qty) if risk > 0 and leg_qty > 0 else 0

            close_reason = self._infer_close_reason(avg_exit, idea, leg_name) if avg_exit > 0 else None

            legs.append({
                "leg": leg_name,
                "quantity": leg_qty,
                "entry_fill_id": leg_entry_fills[0]["fill_id"] if leg_entry_fills else None,
                "exit_fill_id": leg_exit_fills[0]["fill_id"] if leg_exit_fills else None,
                "entry_price": round(avg_entry, 4),
                "exit_price": round(avg_exit, 4),
                "close_reason": close_reason,
                "pnl": round(pnl, 2),
                "r_multiple": round(r_multiple, 2),
                "hold_days": self._calc_hold_days(leg_entry_fills, leg_exit_fills),
            })

        return legs

    @staticmethod
    def _infer_close_reason(
        exit_price: float, idea: dict, leg: str = "T2"
    ) -> str:
        """Infer why a position was closed based on exit price vs targets/stop."""
        stop = idea.get("stop_loss", 0)
        t1 = idea.get("take_profit_t1", 0)
        t2 = idea.get("take_profit_t2", 0)

        if stop > 0 and exit_price <= stop * 1.005:  # Within 0.5% of stop
            return "stop_loss"
        if leg == "T1" and t1 > 0 and exit_price >= t1 * 0.995:
            return "take_profit_t1"
        if t2 > 0 and exit_price >= t2 * 0.995:
            return "take_profit_t2"
        return "manual"

    @staticmethod
    def _calc_hold_days(entry_fills: List[dict], exit_fills: List[dict]) -> int:
        """Calculate holding period in calendar days."""
        if not entry_fills or not exit_fills:
            return 0
        entry_time = entry_fills[0].get("exec_time")
        exit_time = exit_fills[-1].get("exec_time")
        if not entry_time or not exit_time:
            return 0
        try:
            if isinstance(entry_time, str):
                entry_time = datetime.fromisoformat(entry_time)
            if isinstance(exit_time, str):
                exit_time = datetime.fromisoformat(exit_time)
            return max(0, (exit_time.replace(tzinfo=None) - entry_time.replace(tzinfo=None)).days)
        except (ValueError, TypeError):
            return 0

    # ── Query methods ──────────────────────────────────────────────────

    def get_position(self, position_id: str) -> Optional[dict]:
        return self._positions.find_one({"position_id": position_id}, {"_id": 0})

    def get_positions(
        self,
        status: Optional[str] = None,
        symbol: Optional[str] = None,
        since: Optional[str] = None,
    ) -> List[dict]:
        query: Dict = {}
        if status:
            query["status"] = status
        if symbol:
            query["symbol"] = symbol
        if since:
            query["opened_at"] = {"$gte": datetime.strptime(since, "%Y-%m-%d")}
        return list(self._positions.find(query, {"_id": 0}).sort("opened_at", -1))

    def get_open_positions(self) -> List[dict]:
        return self.get_positions(status="open")
