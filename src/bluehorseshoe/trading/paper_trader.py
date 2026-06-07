"""
Paper trading module — submits bracket orders to IBKR paper account
after the prediction pipeline generates scored candidates.
"""
import csv
import logging
import math
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from pymongo.database import Database

from bluehorseshoe.core.config import REPO_ROOT
from bluehorseshoe.data.ibkr_client import IBKRClient
from bluehorseshoe.trading.trade_models import make_idea_id, make_order_ref, normalize_strategy

logger = logging.getLogger(__name__)


@dataclass
class PaperTradeConfig:
    """Configuration for paper trading."""
    total_investment: float = 10000.0
    max_positions: int = 10
    logs_path: str = f"{REPO_ROOT}/src/logs"
    # Slots reserved for the deep_oversold sleeve (of max_positions); remainder
    # shared by legacy strategies. Spillover allowed (idle reserved slots on one
    # side fill from the other). 0 disables reservation (pure global top-N).
    slots_deep_oversold: int = 3


@dataclass
class OrderResult:
    """Result of a single bracket order attempt."""
    symbol: str
    strategy: str
    quantity: int = 0
    entry_price: float = 0.0
    take_profit_price: float = 0.0
    stop_loss_price: float = 0.0
    order_ids: List[int] = field(default_factory=list)
    status: str = "pending"  # pending, submitted, skipped, error
    error: Optional[str] = None
    idea_id: Optional[str] = None
    t1_order_ids: List[int] = field(default_factory=list)
    t2_order_ids: List[int] = field(default_factory=list)
    t1_qty: int = 0
    t2_qty: int = 0
    t1_target: float = 0.0


class PaperTrader:
    """
    Submits bracket orders (entry + take-profit + stop-loss) to IBKR paper account.

    Takes scored candidates from the prediction pipeline, sizes positions,
    checks for duplicates, and submits orders via IBKRClient.
    """

    def __init__(
        self,
        ibkr_client: IBKRClient,
        config: PaperTradeConfig,
        database: Optional[Database] = None,
    ):
        self._client = ibkr_client
        self._config = config
        self._db = database
        self._edge_weights: Optional[Dict[str, float]] = None  # lazy registry-derived alloc weights
        self._collection = database["paper_trades"] if database is not None else None
        self._orders_collection = database["trade_orders"] if database is not None else None
        if self._orders_collection is not None:
            try:
                self._orders_collection.create_index(
                    [("order_ref", 1)], unique=True, name="ux_order_ref"
                )
                self._orders_collection.create_index(
                    [("idea_id", 1)], name="ix_idea_id"
                )
            except Exception as e:
                logger.warning("Failed to create trade_orders indexes: %s", e)

    def execute(
        self,
        candidates: List[dict],
        target_date: str,
        idea_lookup: Optional[Dict[Tuple[str, str], str]] = None,
    ) -> List[OrderResult]:
        """
        Submit split bracket orders for top N candidates.

        Each position is split into two halves:
        - T1 half: take_profit = entry * 1.02 (2% fixed), original stop
        - T2 half: take_profit = original target, original stop

        Args:
            candidates: Sorted list of candidate dicts from swing_predict().
                        Each has: symbol, strategy, close (entry), stop_loss, target, t1_target
            target_date: Date string (YYYY-MM-DD) for logging and duplicate detection.
            idea_lookup: Optional mapping of (symbol, strategy_display) -> idea_id
                         for linking orders to trade ideas.

        Returns:
            List of OrderResult for each candidate processed.
        """
        if idea_lookup is None:
            idea_lookup = {}

        # Drop tracking-only sleeves: they flow to the hypothesis engine for forward-R
        # but must never reach live broker slots (paper_tradeable=False). Candidates key
        # 'strategy' by display_name, so map those back through the registry.
        from bluehorseshoe.analysis.strategy_registry import get_all_strategies
        no_trade = {s.display_name for s in get_all_strategies() if not s.paper_tradeable}
        if no_trade:
            candidates = [c for c in candidates if c.get("strategy") not in no_trade]

        # Treat max_positions as "have at most this many on the book," not
        # "submit this many now." Without this, running -p with N still-working
        # brackets from yesterday submits N more today and the book grows
        # unbounded across days.
        occupied = self._get_occupied_symbols()
        if occupied is None:
            # Broker unreachable. Fail closed — don't size off stale assumptions.
            logger.error(
                "Paper trading: broker unreachable; skipping submission of "
                "%d candidates", len(candidates),
            )
            return []

        slots_available = max(0, self._config.max_positions - len(occupied))
        eligible = [c for c in candidates if c.get("symbol", "") not in occupied]
        top = self._select_with_reservation(eligible, occupied, slots_available)
        per_position = self._config.total_investment / self._config.max_positions

        logger.info(
            "Paper trading: %d occupied, %d slots available, "
            "%d/%d candidates eligible after dedup, submitting %d",
            len(occupied), slots_available,
            len(eligible), len(candidates), len(top),
        )

        results: List[OrderResult] = []
        # Overlapping sleeves (e.g. DeepOS and DeepOS+HA) can both surface the same
        # symbol in one run. Candidates arrive score-sorted, so the first occurrence
        # wins its slot; any later same-symbol candidate is skipped to avoid placing
        # two bracket orders (double exposure) on one name. Hypothesis-engine tracking
        # is unaffected — it reads the frozen per-strategy scores, not these orders.
        submitted_this_run: Set[str] = set()

        for cand in top:
            symbol = cand.get("symbol", "")
            strategy = cand.get("strategy", "unknown")
            entry_price = cand.get("close", 0)
            stop_loss = cand.get("stop_loss", 0)
            take_profit = cand.get("target", 0)
            t1_target = cand.get("t1_target", entry_price * 1.02 if entry_price > 0 else 0)
            cand_idea_id = idea_lookup.get((symbol, strategy))

            if symbol in submitted_this_run:
                results.append(OrderResult(
                    symbol=symbol, strategy=strategy, entry_price=entry_price,
                    stop_loss_price=stop_loss, take_profit_price=take_profit,
                    status="skipped",
                    error="symbol already submitted this run (other sleeve)",
                    idea_id=cand_idea_id,
                ))
                continue

            # Validate prices
            if not self._validate_prices(entry_price, stop_loss, take_profit):
                results.append(OrderResult(
                    symbol=symbol, strategy=strategy, entry_price=entry_price,
                    stop_loss_price=stop_loss, take_profit_price=take_profit,
                    status="skipped", error="invalid prices",
                    idea_id=cand_idea_id,
                ))
                continue

            # Check duplicates
            if self._is_duplicate(symbol, target_date, strategy):
                results.append(OrderResult(
                    symbol=symbol, strategy=strategy, entry_price=entry_price,
                    stop_loss_price=stop_loss, take_profit_price=take_profit,
                    status="skipped", error="duplicate",
                    idea_id=cand_idea_id,
                ))
                continue

            # Past every pre-flight gate: this symbol now owns its slot for the run.
            submitted_this_run.add(symbol)

            # Calculate total position size then split into halves
            total_quantity = math.floor(per_position / entry_price)
            if total_quantity < 2:
                # Need at least 2 shares to split; fall back to single order
                if total_quantity < 1:
                    results.append(OrderResult(
                        symbol=symbol, strategy=strategy, entry_price=entry_price,
                        stop_loss_price=stop_loss, take_profit_price=take_profit,
                        status="skipped", error="insufficient capital for 1 share",
                        idea_id=cand_idea_id,
                    ))
                    continue
                # 1 share: place single T2 order
                order_result = self._client.place_bracket_order(
                    symbol=symbol, quantity=1, limit_price=entry_price,
                    take_profit_price=take_profit, stop_loss_price=stop_loss,
                )
                t2_ids = order_result.get("order_ids", [])
                results.append(OrderResult(
                    symbol=symbol, strategy=strategy, quantity=1,
                    entry_price=entry_price, stop_loss_price=stop_loss,
                    take_profit_price=take_profit,
                    order_ids=t2_ids,
                    status=order_result.get("status", "error"),
                    error=order_result.get("error"),
                    idea_id=cand_idea_id,
                    t2_order_ids=t2_ids, t2_qty=1,
                    t1_target=t1_target,
                ))
                continue

            t1_qty = total_quantity // 2
            t2_qty = total_quantity - t1_qty

            all_order_ids = []
            combined_status = "submitted"
            combined_error = None

            # T1 half: take profit at entry * 1.02
            t1_result = self._client.place_bracket_order(
                symbol=symbol, quantity=t1_qty, limit_price=entry_price,
                take_profit_price=t1_target, stop_loss_price=stop_loss,
            )
            t1_ids = t1_result.get("order_ids", [])
            all_order_ids.extend(t1_ids)
            if t1_result.get("status") == "error":
                combined_status = "error"
                combined_error = f"T1: {t1_result.get('error', 'unknown')}"

            # T2 half: take profit at original target
            t2_result = self._client.place_bracket_order(
                symbol=symbol, quantity=t2_qty, limit_price=entry_price,
                take_profit_price=take_profit, stop_loss_price=stop_loss,
            )
            t2_ids = t2_result.get("order_ids", [])
            all_order_ids.extend(t2_ids)
            if t2_result.get("status") == "error":
                t2_err = f"T2: {t2_result.get('error', 'unknown')}"
                combined_error = f"{combined_error}; {t2_err}" if combined_error else t2_err
                combined_status = "error"

            results.append(OrderResult(
                symbol=symbol, strategy=strategy, quantity=total_quantity,
                entry_price=entry_price, stop_loss_price=stop_loss,
                take_profit_price=take_profit,
                order_ids=all_order_ids, status=combined_status,
                error=combined_error,
                idea_id=cand_idea_id,
                t1_order_ids=t1_ids, t2_order_ids=t2_ids,
                t1_qty=t1_qty, t2_qty=t2_qty,
                t1_target=t1_target,
            ))

        # Log results
        self._log_csv(results, target_date)
        self._log_mongo(results, target_date)
        self._log_trade_orders(results, target_date)

        return results

    def _get_occupied_symbols(self) -> Optional[Set[str]]:
        """Symbols the broker already considers ours, by either an open
        position or a working BUY entry order. Returns None if the broker
        is unreachable, so the caller can fail closed.

        SELL legs (bracket exit orders) don't get counted separately — the
        parent position is already counted via get_positions().
        """
        # Reachability test mirrors bh_swing.trading.reconciler — a blank
        # account_id is how IBKRClient signals "the call didn't reach the
        # gateway" (it swallows exceptions and returns a stub).
        account = self._client.get_account_summary()
        if not account.get("account_id"):
            return None

        occupied: Set[str] = set()
        for p in self._client.get_positions():
            if p.get("position", 0) != 0 and p.get("symbol"):
                occupied.add(p["symbol"])

        for trade in self._client.get_open_trades():
            contract = getattr(trade, "contract", None)
            order = getattr(trade, "order", None)
            if contract is None or order is None:
                continue
            action = getattr(order, "action", "")
            symbol = getattr(contract, "symbol", "")
            if action == "BUY" and symbol:
                occupied.add(symbol)

        return occupied

    def _occupied_by_strategy(self, occupied: Set[str], deepos_display: str) -> int:
        """How many currently-occupied symbols were opened by deep_oversold.

        The broker doesn't track strategy, so map each occupied symbol to the
        strategy on its most-recent ``paper_trades`` record. Symbols with no
        record bucket as legacy — that protects the DeepOS reservation from
        phantom occupancy rather than silently eating its slots.
        """
        if self._collection is None or not occupied:
            return 0
        deep = 0
        for sym in occupied:
            doc = self._collection.find_one({"symbol": sym}, sort=[("date", -1)])
            if doc and doc.get("strategy") == deepos_display:
                deep += 1
        return deep

    def _edge_weight_map(self) -> Dict[str, float]:
        """``{display_name: edge_weight}`` for cross-sleeve allocation ranking.

        Derived from the registry at call time (not stamped on candidates) so it is
        independent of which path built the candidate (``-p`` assembler vs ``-r``
        regenerate). Unregistered sources (e.g. ``Connors``) are absent → callers
        default them to 0.0 → they fill only leftover capacity behind validated sleeves.
        """
        if self._edge_weights is None:
            from bluehorseshoe.analysis.strategy_registry import get_all_strategies
            self._edge_weights = {s.display_name: s.edge_weight for s in get_all_strategies()}
        return self._edge_weights

    def _select_with_reservation(
        self, eligible: List[dict], occupied: Set[str], slots_available: int
    ) -> List[dict]:
        """Choose which eligible candidates to submit, honoring the deep_oversold
        slot reservation with spillover.

        DeepOS gets up to ``slots_deep_oversold`` concurrent positions; legacy
        strategies share the rest. Reserved-but-idle slots on one side spill over
        to the other so capital isn't idle. Everything stays capped at the global
        ``slots_available`` — the "at most N on the book" invariant is preserved
        by counting *existing* per-strategy occupancy, not just new submissions.
        """
        if slots_available <= 0:
            return []
        deep_reserved = max(0, min(self._config.slots_deep_oversold,
                                   self._config.max_positions))
        if deep_reserved == 0:
            # Reservation disabled → global top-N ranked by edge-weighted score
            # (score * validated per-trade R), so the higher-edge sleeve wins a slot
            # even when a weaker sleeve has a higher raw score. Sources with no
            # validated edge (weight 0 — incl. the unregistered "Connors" sleeve)
            # sort last and only fill leftover capacity.
            wmap = self._edge_weight_map()
            return sorted(
                eligible,
                key=lambda c: c.get("score", 0.0) * wmap.get(c.get("strategy", ""), 0.0),
                reverse=True,
            )[:slots_available]

        # Local import: keep the trading layer decoupled from analysis at import time.
        from bluehorseshoe.analysis.strategy_registry import get_strategy
        deepos_display = get_strategy("deep_oversold").display_name
        legacy_reserved = max(0, self._config.max_positions - deep_reserved)

        deep_occupied = self._occupied_by_strategy(occupied, deepos_display)
        legacy_occupied = len(occupied) - deep_occupied
        deep_slots = max(0, deep_reserved - deep_occupied)
        legacy_slots = max(0, legacy_reserved - legacy_occupied)

        deep_cands = [c for c in eligible if c.get("strategy") == deepos_display]
        legacy_cands = [c for c in eligible if c.get("strategy") != deepos_display]

        # Reserved (guaranteed) picks first; if the global cap binds, highest score wins.
        guaranteed = sorted(
            deep_cands[:deep_slots] + legacy_cands[:legacy_slots],
            key=lambda c: c.get("score", 0), reverse=True,
        )
        selected = guaranteed[:slots_available]

        # Spillover: fill remaining global slots from leftover candidates by score.
        if len(selected) < slots_available:
            leftover = sorted(
                deep_cands[deep_slots:] + legacy_cands[legacy_slots:],
                key=lambda c: c.get("score", 0), reverse=True,
            )
            selected += leftover[: slots_available - len(selected)]

        n_deep = sum(1 for c in selected if c.get("strategy") == deepos_display)
        logger.info(
            "Slot reservation: DeepOS %d reserved (%d occ → %d open), "
            "legacy %d reserved (%d occ → %d open); selected %d (DeepOS %d, legacy %d)",
            deep_reserved, deep_occupied, deep_slots,
            legacy_reserved, legacy_occupied, legacy_slots,
            len(selected), n_deep, len(selected) - n_deep,
        )
        return selected

    @staticmethod
    def _validate_prices(
        entry: float, stop_loss: float, take_profit: float
    ) -> bool:
        """Check that prices are positive and logically consistent."""
        if entry <= 0 or stop_loss <= 0 or take_profit <= 0:
            return False
        if take_profit <= entry:
            return False
        if stop_loss >= entry:
            return False
        return True

    def _is_duplicate(self, symbol: str, date: str, strategy: str) -> bool:
        """Check if an order for this symbol/date/strategy already exists."""
        if self._collection is None:
            return False
        return (
            self._collection.find_one(
                {"symbol": symbol, "date": date, "strategy": strategy}
            )
            is not None
        )

    def _log_csv(self, results: List[OrderResult], target_date: str) -> None:
        """Append order results to a date-stamped CSV file."""
        csv_path = os.path.join(
            self._config.logs_path, f"paper_trades_{target_date}.csv"
        )
        file_exists = os.path.exists(csv_path)

        try:
            with open(csv_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow([
                        "timestamp", "symbol", "strategy", "quantity",
                        "entry_price", "take_profit", "stop_loss",
                        "order_ids", "status", "error",
                    ])
                for r in results:
                    writer.writerow([
                        datetime.now().isoformat(),
                        r.symbol,
                        r.strategy,
                        r.quantity,
                        r.entry_price,
                        r.take_profit_price,
                        r.stop_loss_price,
                        "|".join(str(i) for i in r.order_ids),
                        r.status,
                        r.error or "",
                    ])
            logger.info("Paper trade log written to %s", csv_path)
        except OSError as e:
            logger.error("Failed to write paper trade CSV: %s", e)

    def _log_mongo(self, results: List[OrderResult], target_date: str) -> None:
        """Upsert order results into the paper_trades MongoDB collection."""
        if self._collection is None:
            return

        for r in results:
            doc = {
                "symbol": r.symbol,
                "date": target_date,
                "strategy": r.strategy,
                "quantity": r.quantity,
                "entry_price": r.entry_price,
                "take_profit_price": r.take_profit_price,
                "stop_loss_price": r.stop_loss_price,
                "order_ids": r.order_ids,
                "status": r.status,
                "error": r.error,
                "updated_at": datetime.now(),
            }
            try:
                self._collection.update_one(
                    {"symbol": r.symbol, "date": target_date, "strategy": r.strategy},
                    {"$set": doc},
                    upsert=True,
                )
            except Exception as e:
                logger.error("Failed to log paper trade to MongoDB for %s: %s", r.symbol, e)

    def _log_trade_orders(self, results: List[OrderResult], target_date: str) -> None:
        """Write normalized trade_orders documents (one per leg) linked to trade_ideas."""
        if self._orders_collection is None:
            return

        for r in results:
            if r.status not in ("submitted",):
                continue
            if not r.idea_id:
                continue

            now = datetime.now()

            # Write T1 order doc if T1 was placed
            if r.t1_order_ids:
                t1_ref = make_order_ref(r.idea_id, "T1")
                t1_doc = {
                    "order_ref": t1_ref,
                    "idea_id": r.idea_id,
                    "symbol": r.symbol,
                    "leg": "T1",
                    "broker_order_ids": r.t1_order_ids,
                    "quantity": r.t1_qty,
                    "limit_price": r.entry_price,
                    "take_profit_price": r.t1_target,
                    "stop_loss_price": r.stop_loss_price,
                    "status": "submitted",
                    "submitted_at": now,
                    "updated_at": now,
                }
                try:
                    self._orders_collection.update_one(
                        {"order_ref": t1_ref}, {"$set": t1_doc}, upsert=True,
                    )
                except Exception as e:
                    logger.error("Failed to log T1 trade_order for %s: %s", r.symbol, e)

            # Write T2 order doc
            if r.t2_order_ids:
                t2_ref = make_order_ref(r.idea_id, "T2")
                t2_doc = {
                    "order_ref": t2_ref,
                    "idea_id": r.idea_id,
                    "symbol": r.symbol,
                    "leg": "T2",
                    "broker_order_ids": r.t2_order_ids,
                    "quantity": r.t2_qty,
                    "limit_price": r.entry_price,
                    "take_profit_price": r.take_profit_price,
                    "stop_loss_price": r.stop_loss_price,
                    "status": "submitted",
                    "submitted_at": now,
                    "updated_at": now,
                }
                try:
                    self._orders_collection.update_one(
                        {"order_ref": t2_ref}, {"$set": t2_doc}, upsert=True,
                    )
                except Exception as e:
                    logger.error("Failed to log T2 trade_order for %s: %s", r.symbol, e)
