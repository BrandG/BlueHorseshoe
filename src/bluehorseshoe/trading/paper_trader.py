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

from bluehorseshoe.analysis.constants import RANGE_SUPPORT_RATCHET_ATR, RANGE_SUPPORT_STOP_MULT
from bluehorseshoe.core.config import REPO_ROOT
from bluehorseshoe.data.ibkr_client import IBKRClient
from bluehorseshoe.trading.trade_models import make_idea_id, make_order_ref, normalize_strategy

# range_support exit is a native, broker-managed trailing stop: initial trigger at the 1xATR entry
# stop, trailing distance at RANGE_SUPPORT_RATCHET_ATR (2xATR). The trail distance is this ratio
# times the initial 1xATR stop distance, so both track the same ATR the strategy priced the stop on.
_RANGE_SUPPORT_TRAIL_OVER_STOP = RANGE_SUPPORT_RATCHET_ATR / RANGE_SUPPORT_STOP_MULT

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
    # Conviction-weighted sizing: split the pot proportional to sleeve edge_weight
    # (validated per-trade R) rather than flat-equal. Pot unchanged → same total
    # capital, tilted distribution. Reduces to flat for a single-sleeve book.
    conviction_sizing: bool = True
    # Per-position cap as a multiple of the equal-weight slot; bounds concentration.
    max_position_mult: float = 2.5
    # Fill-anchored execution: -p stages intended orders, --execute-open submits
    # marketable entries and anchors exits to the actual fill. False preserves the
    # legacy all-at-once bracket path.
    fill_anchored_execution: bool = False
    # Fractional shares: deploy exact target dollars instead of flooring to whole
    # shares. DEFAULT FALSE — IBKR rejects API fractional orders (Error 10243); see
    # Settings.paper_fractional_shares. Re-enable only after account-level fractional
    # is turned on and src/verify_fractional_bracket.py returns PASS.
    fractional_shares: bool = False
    fractional_precision: int = 4    # decimals to round fractional share quantities
    min_order_value: float = 1.0     # skip positions with notional below this ($)


@dataclass
class OrderResult:
    """Result of a single bracket order attempt."""
    symbol: str
    strategy: str
    quantity: float = 0.0  # float: fractional shares supported
    entry_price: float = 0.0
    take_profit_price: float = 0.0
    stop_loss_price: float = 0.0
    order_ids: List[int] = field(default_factory=list)
    status: str = "pending"  # pending, staged, submitted, partial, skipped, error
    error: Optional[str] = None
    idea_id: Optional[str] = None
    t1_order_ids: List[int] = field(default_factory=list)
    t2_order_ids: List[int] = field(default_factory=list)
    t1_qty: float = 0.0
    t2_qty: float = 0.0
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
        self._staged_collection = None
        if database is not None:
            try:
                self._staged_collection = database["staged_orders"]
            except Exception as e:
                logger.warning("Failed to initialize staged_orders collection: %s", e)
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
        if self._staged_collection is not None:
            try:
                self._staged_collection.create_index(
                    [("date", 1), ("symbol", 1), ("strategy", 1)],
                    unique=True,
                    name="ux_staged_order",
                )
                self._staged_collection.create_index(
                    [("date", 1), ("status", 1)],
                    name="ix_staged_date_status",
                )
            except Exception as e:
                logger.warning("Failed to create staged_orders indexes: %s", e)

    def stage_orders(
        self,
        candidates: List[dict],
        target_date: str,
        idea_lookup: Optional[Dict[Tuple[str, str], str]] = None,
    ) -> List[OrderResult]:
        """Persist intended orders for fill-anchored execution.

        This is deliberately broker-free: the open runner re-checks gateway
        reachability, occupancy, and duplicate state immediately before it places
        marketable entries.
        """
        if idea_lookup is None:
            idea_lookup = {}
        if self._staged_collection is None:
            logger.error("Fill-anchored staging requires MongoDB staged_orders collection")
            return []

        top = self._rank_stage_candidates(candidates)
        size_for = self._position_sizes(top)
        results: List[OrderResult] = []
        submitted_this_run: Set[str] = set()

        for rank, cand in enumerate(top, start=1):
            symbol = cand.get("symbol", "")
            strategy = cand.get("strategy", "unknown")
            entry_model = cand.get("close", 0)
            stop_model = cand.get("stop_loss", 0)
            target_model = cand.get("target", 0)
            t1_target = cand.get("t1_target", entry_model * 1.02 if entry_model > 0 else 0)
            cand_idea_id = idea_lookup.get((symbol, strategy))

            if symbol in submitted_this_run:
                results.append(OrderResult(
                    symbol=symbol, strategy=strategy, entry_price=entry_model,
                    stop_loss_price=stop_model, take_profit_price=target_model,
                    status="skipped",
                    error="symbol already staged this run (other sleeve)",
                    idea_id=cand_idea_id,
                ))
                continue
            if not self._validate_prices(entry_model, stop_model, target_model):
                results.append(OrderResult(
                    symbol=symbol, strategy=strategy, entry_price=entry_model,
                    stop_loss_price=stop_model, take_profit_price=target_model,
                    status="skipped", error="invalid prices",
                    idea_id=cand_idea_id,
                ))
                continue
            if self._is_duplicate(symbol, target_date, strategy):
                results.append(OrderResult(
                    symbol=symbol, strategy=strategy, entry_price=entry_model,
                    stop_loss_price=stop_model, take_profit_price=target_model,
                    status="skipped", error="duplicate",
                    idea_id=cand_idea_id,
                ))
                continue

            total_quantity, t1_qty, t2_qty = self._split_quantity(
                size_for.get(id(cand), 0.0), entry_model
            )
            if total_quantity <= 0:
                results.append(OrderResult(
                    symbol=symbol, strategy=strategy, entry_price=entry_model,
                    stop_loss_price=stop_model, take_profit_price=target_model,
                    status="skipped", error="insufficient capital for minimum order",
                    idea_id=cand_idea_id,
                ))
                continue

            submitted_this_run.add(symbol)
            r_offset = entry_model - stop_model
            # No-take-profit sleeve (range_support): target<=0 → stop-only exit, no T1/T2 targets.
            no_take_profit = target_model <= 0
            tp_offset = 0.0 if no_take_profit else (target_model - entry_model)
            t1_offset = 0.0 if no_take_profit else (t1_target - entry_model if t1_target else 0.0)
            doc = {
                "date": target_date,
                "symbol": symbol,
                "strategy": strategy,
                "total_qty": float(total_quantity),
                "t1_qty": float(t1_qty),
                "t2_qty": float(t2_qty),
                "entry_model": float(entry_model),
                "R": float(r_offset),
                "tp_offset": float(tp_offset),
                "t1_offset": float(t1_offset),
                "no_take_profit": bool(no_take_profit),
                "idea_id": cand_idea_id,
                "rank": rank,
                "status": "staged",
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
            }
            try:
                self._staged_collection.update_one(
                    {"date": target_date, "symbol": symbol, "strategy": strategy},
                    {"$set": doc},
                    upsert=True,
                )
            except Exception as e:
                logger.error("Failed to stage order for %s: %s", symbol, e)
                results.append(OrderResult(
                    symbol=symbol, strategy=strategy, quantity=total_quantity,
                    entry_price=entry_model, stop_loss_price=stop_model,
                    take_profit_price=target_model, status="error", error=str(e),
                    idea_id=cand_idea_id, t1_qty=t1_qty, t2_qty=t2_qty,
                    t1_target=t1_target,
                ))
                continue

            results.append(OrderResult(
                symbol=symbol, strategy=strategy, quantity=total_quantity,
                entry_price=entry_model, stop_loss_price=stop_model,
                take_profit_price=target_model, status="staged",
                idea_id=cand_idea_id, t1_qty=t1_qty, t2_qty=t2_qty,
                t1_target=t1_target,
            ))

        self._log_csv(results, target_date)
        logger.info("Fill-anchored staging complete: %d staged", sum(
            1 for r in results if r.status == "staged"
        ))
        return results

    def execute_open(
        self,
        target_date: str,
        timeout_s: float = 120.0,
        poll_interval_s: float = 1.0,
    ) -> List[OrderResult]:
        """Execute staged orders, then attach exits anchored to the actual fill."""
        if self._staged_collection is None:
            logger.error("Fill-anchored execute-open requires MongoDB staged_orders collection")
            return []

        try:
            from bh_swing.trading import safety  # pylint: disable=import-outside-toplevel
            ok, reason = safety.kill_switch_inactive()
        except Exception as e:
            ok, reason = False, f"kill switch check failed: {e}"
        if not ok:
            logger.error("Paper trading execute-open halted: %s", reason)
            return []

        occupied = self._get_occupied_symbols()
        if occupied is None:
            logger.error("Paper trading execute-open: broker unreachable; failing closed")
            return []

        staged = sorted(self._staged_collection.find({
            "date": target_date,
            "status": "staged",
        }), key=lambda d: (
            int(d.get("rank", self._config.max_positions + 1) or self._config.max_positions + 1),
            str(d.get("symbol", "")),
        ))
        slots = max(0, self._config.max_positions - len(occupied))
        results: List[OrderResult] = []
        for doc in staged:
            if slots <= 0:
                result = self._skip_staged_doc(doc, "position cap reached")
                results.append(result)
                continue
            result = self._execute_staged_doc(
                doc, target_date, occupied, timeout_s, poll_interval_s
            )
            results.append(result)
            if result.status in ("submitted", "partial"):
                occupied.add(result.symbol)
                slots -= 1

        self._log_csv(results, target_date)
        self._log_mongo(results, target_date)
        logger.info("Paper trading execute-open complete: %d live, %d partial, %d skipped/errors",
                    sum(1 for r in results if r.status == "submitted"),
                    sum(1 for r in results if r.status == "partial"),
                    sum(1 for r in results if r.status not in ("submitted", "partial")))
        return results

    def _skip_staged_doc(self, doc: dict, reason: str) -> OrderResult:
        symbol = doc.get("symbol", "")
        strategy = doc.get("strategy", "unknown")
        total_qty = int(math.floor(float(doc.get("total_qty", 0.0) or 0.0)))
        entry_model = float(doc.get("entry_model", 0.0) or 0.0)
        try:
            self._staged_collection.update_one(
                {"_id": doc.get("_id")},
                {"$set": {"status": "skipped", "error": reason, "updated_at": datetime.now()}},
            )
        except Exception as e:
            logger.error("Failed to update staged order for %s: %s", symbol, e)
        logger.info("Skipping staged %s: %s", symbol, reason)
        return OrderResult(
            symbol=symbol, strategy=strategy, quantity=total_qty,
            entry_price=entry_model, status="skipped", error=reason,
            idea_id=doc.get("idea_id"),
        )

    def _rank_stage_candidates(self, candidates: List[dict]) -> List[dict]:
        from bluehorseshoe.analysis.strategy_registry import get_all_strategies
        no_trade = {s.display_name for s in get_all_strategies() if not s.paper_tradeable}
        eligible = [c for c in candidates if c.get("strategy") not in no_trade]
        return self._select_with_reservation(eligible, set(), self._config.max_positions)

    def _execute_staged_doc(
        self,
        doc: dict,
        target_date: str,
        occupied: Set[str],
        timeout_s: float,
        poll_interval_s: float,
    ) -> OrderResult:
        symbol = doc.get("symbol", "")
        strategy = doc.get("strategy", "unknown")
        entry_model = float(doc.get("entry_model", 0.0) or 0.0)
        r_offset = float(doc.get("R", 0.0) or 0.0)
        tp_offset = float(doc.get("tp_offset", 0.0) or 0.0)
        t1_offset = float(doc.get("t1_offset", 0.0) or 0.0)
        total_qty = int(math.floor(float(doc.get("total_qty", 0.0) or 0.0)))
        t1_qty_model = int(math.floor(float(doc.get("t1_qty", 0.0) or 0.0)))
        t2_qty_model = int(math.floor(float(doc.get("t2_qty", 0.0) or 0.0)))
        idea_id = doc.get("idea_id")
        no_take_profit = bool(doc.get("no_take_profit", False))   # range_support: stop-only exit

        def _mark(status: str, error: Optional[str] = None, extra: Optional[dict] = None):
            update = {"status": status, "updated_at": datetime.now()}
            if error:
                update["error"] = error
            if extra:
                update.update(extra)
            try:
                self._staged_collection.update_one({"_id": doc.get("_id")}, {"$set": update})
            except Exception as e:
                logger.error("Failed to update staged order for %s: %s", symbol, e)

        if symbol in occupied:
            msg = "symbol already on broker book at open"
            logger.info("Skipping staged %s: %s", symbol, msg)
            _mark("skipped", msg)
            return OrderResult(symbol=symbol, strategy=strategy, quantity=total_qty,
                               entry_price=entry_model, status="skipped", error=msg,
                               idea_id=idea_id)
        if self._is_duplicate(symbol, target_date, strategy):
            msg = "duplicate"
            logger.info("Skipping staged %s: %s", symbol, msg)
            _mark("skipped", msg)
            return OrderResult(symbol=symbol, strategy=strategy, quantity=total_qty,
                               entry_price=entry_model, status="skipped", error=msg,
                               idea_id=idea_id)
        if total_qty < 1:
            msg = "staged quantity below 1 whole share"
            logger.warning("Skipping staged %s: %s", symbol, msg)
            _mark("skipped", msg)
            return OrderResult(symbol=symbol, strategy=strategy, quantity=0,
                               entry_price=entry_model, status="skipped", error=msg,
                               idea_id=idea_id)

        entry_limit = round(entry_model * 1.02, 2)
        entry = self._client.place_entry_only(symbol, total_qty, entry_limit, tif="DAY")
        if entry.get("status") == "error":
            err = entry.get("error", "entry placement failed")
            logger.error("Entry placement failed for %s: %s", symbol, err)
            _mark("error", err)
            return OrderResult(symbol=symbol, strategy=strategy, quantity=total_qty,
                               entry_price=entry_model, status="error", error=err,
                               idea_id=idea_id)

        trade = entry.get("trade")
        entry_order_id = entry.get("order_id", 0)
        filled_qty, avg_fill, filled_status = self._wait_for_fill(
            trade, timeout_s=timeout_s, poll_interval_s=poll_interval_s
        )

        if filled_qty <= 0:
            logger.warning("Entry for %s did not fill before timeout; cancelling", symbol)
            self._client.cancel_order(entry_order_id)
            _mark("expired", "no fill before timeout", {"entry_order_id": entry_order_id})
            return OrderResult(symbol=symbol, strategy=strategy, quantity=0,
                               entry_price=entry_model, status="skipped",
                               error="no fill before timeout", idea_id=idea_id)

        is_partial = filled_qty < total_qty
        if is_partial:
            logger.warning("Entry for %s partially filled %s/%s; cancelling remainder",
                           symbol, filled_qty, total_qty)
            self._client.cancel_order(entry_order_id)

        stop_fill = round(avg_fill - r_offset, 2)
        t1_fill = round(avg_fill + t1_offset, 2) if (t1_offset and not no_take_profit) else 0.0
        tp_fill = 0.0 if no_take_profit else round(avg_fill + tp_offset, 2)
        t1_qty, t2_qty = self._split_filled_quantities(
            filled_qty, total_qty, t1_qty_model, t2_qty_model
        )
        if no_take_profit:
            t1_qty, t2_qty = 0, filled_qty      # single full-position leg, recorded as T2
        exit_pairs = []
        if no_take_profit:
            # range_support: one native trailing stop on the full filled qty, no take-profit legs.
            # Initial trigger at the 1xATR stop (stop_fill); trails at 2xATR (2*r_offset), up-only,
            # broker-managed — replaces the retired monitor ratchet (blocked by IBKR Error 103).
            exit_pairs.append((
                "B",
                [{"leg": "STOP_B", "order_type": "TRAIL", "quantity": filled_qty,
                  "price": stop_fill,
                  "trail_amount": round(_RANGE_SUPPORT_TRAIL_OVER_STOP * r_offset, 2)}],
            ))
        else:
            if t1_qty > 0:
                exit_pairs.append((
                    "A",
                    [
                        {"leg": "T1", "order_type": "LMT", "quantity": t1_qty, "price": t1_fill},
                        {"leg": "STOP_A", "order_type": "STP", "quantity": t1_qty, "price": stop_fill},
                    ],
                ))
            if t2_qty > 0:
                exit_pairs.append((
                    "B",
                    [
                        {"leg": "T2", "order_type": "LMT", "quantity": t2_qty, "price": tp_fill},
                        {"leg": "STOP_B", "order_type": "STP", "quantity": t2_qty, "price": stop_fill},
                    ],
                ))

        base_oca_group = f"BH_{target_date}_{symbol}_{strategy}".replace(" ", "_")[:30]
        order_ids = {}
        oca_groups = {}
        for suffix, legs in exit_pairs:
            oca_group = f"{base_oca_group}_{suffix}"[:32]
            exits = self._client.place_oca_exits(symbol, oca_group, legs)
            if exits.get("status") == "error":
                err = exits.get("error", "exit placement failed")
                logger.error("Exit placement failed for %s after fill: %s", symbol, err)
                _mark("error", err, {
                    "entry_order_id": entry_order_id,
                    "avgFillPrice": avg_fill,
                    "filled_qty": filled_qty,
                })
                return OrderResult(symbol=symbol, strategy=strategy, quantity=filled_qty,
                                   entry_price=avg_fill, stop_loss_price=stop_fill,
                                   take_profit_price=tp_fill, status="error",
                                   error=err, idea_id=idea_id, t1_qty=t1_qty,
                                   t2_qty=t2_qty, t1_target=t1_fill)

            pair_order_ids = exits.get("order_ids", {})
            if isinstance(pair_order_ids, list):
                pair_order_ids = {leg["leg"]: oid for leg, oid in zip(legs, pair_order_ids)}
            order_ids.update(pair_order_ids)
            oca_groups[suffix] = oca_group

        result_status = "partial" if is_partial else "submitted"
        result = OrderResult(
            symbol=symbol, strategy=strategy, quantity=filled_qty,
            entry_price=avg_fill, stop_loss_price=stop_fill,
            take_profit_price=tp_fill,
            order_ids=[entry_order_id] + list(order_ids.values()),
            status=result_status, idea_id=idea_id,
            t1_order_ids=([entry_order_id, order_ids.get("T1"), order_ids.get("STOP_A")]
                          if t1_qty > 0 else []),
            t2_order_ids=([entry_order_id, order_ids.get("T2"), order_ids.get("STOP_B")]
                          if t2_qty > 0 else []),
            t1_qty=t1_qty, t2_qty=t2_qty, t1_target=t1_fill,
        )
        result.t1_order_ids = [oid for oid in result.t1_order_ids if oid]
        result.t2_order_ids = [oid for oid in result.t2_order_ids if oid]
        self._log_trade_orders([result], target_date)
        _mark("partial" if is_partial else "filled", None, {
            "entry_order_id": entry_order_id,
            "exit_order_ids": order_ids,
            "oca_groups": oca_groups,
            "avgFillPrice": avg_fill,
            "filled_qty": filled_qty,
            "stop_fill": stop_fill,
            "t1_fill": t1_fill,
            "tp_fill": tp_fill,
        })
        return result

    def _wait_for_fill(
        self, trade, timeout_s: float, poll_interval_s: float
    ) -> Tuple[int, float, str]:
        elapsed = 0.0
        poll = max(0.1, poll_interval_s)
        while elapsed < timeout_s:
            qty, avg, status = self._fill_snapshot(trade)
            if status == "Filled" and qty > 0:
                return qty, avg, status
            self._client.sleep(min(poll, max(0.0, timeout_s - elapsed)))
            elapsed += poll
        return self._fill_snapshot(trade)

    @staticmethod
    def _fill_snapshot(trade) -> Tuple[int, float, str]:
        order_status = getattr(trade, "orderStatus", None)
        status = getattr(order_status, "status", "") if order_status is not None else ""
        filled = getattr(order_status, "filled", 0) if order_status is not None else 0
        avg = getattr(order_status, "avgFillPrice", 0.0) if order_status is not None else 0.0
        try:
            filled_qty = int(math.floor(float(filled or 0)))
        except (TypeError, ValueError):
            filled_qty = 0
        try:
            avg_fill = float(avg or 0.0)
        except (TypeError, ValueError):
            avg_fill = 0.0
        return filled_qty, avg_fill, status

    @staticmethod
    def _split_filled_quantities(
        filled_qty: int, total_qty: int, t1_qty_model: int, t2_qty_model: int
    ) -> Tuple[int, int]:
        if filled_qty <= 0:
            return 0, 0
        if t1_qty_model <= 0:
            return 0, filled_qty
        if total_qty <= 0:
            return 0, filled_qty
        t1_qty = int(math.floor(filled_qty * (t1_qty_model / total_qty)))
        if t1_qty <= 0 and filled_qty > 1:
            t1_qty = 1
        t1_qty = min(t1_qty, filled_qty)
        t2_qty = filled_qty - t1_qty
        if t2_qty <= 0 and t1_qty > 0 and filled_qty > 1:
            t1_qty -= 1
            t2_qty = 1
        return t1_qty, t2_qty

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
        # Conviction-weighted sizing: distribute the pot (what flat sizing would
        # deploy for this many slots) proportional to each sleeve's validated edge.
        size_for = self._position_sizes(top)

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

            # Calculate total position size then split into halves (fractional-aware)
            total_quantity, t1_qty, t2_qty = self._split_quantity(
                size_for.get(id(cand), 0.0), entry_price
            )
            if total_quantity <= 0:
                results.append(OrderResult(
                    symbol=symbol, strategy=strategy, entry_price=entry_price,
                    stop_loss_price=stop_loss, take_profit_price=take_profit,
                    status="skipped", error="insufficient capital for minimum order",
                    idea_id=cand_idea_id,
                ))
                continue

            # No-take-profit sleeve (range_support): one entry + 1-ATR stop, NO target.
            # The exit is a native broker-managed trailing stop (initial trigger at the 1xATR
            # stop, trailing at 2xATR) — replaces the retired monitor ratchet (IBKR Error 103
            # blocked cross-session stop modifies). Single 2-leg bracket, no T1/T2 scale-out.
            if take_profit <= 0:
                trail_amount = round(
                    _RANGE_SUPPORT_TRAIL_OVER_STOP * (entry_price - stop_loss), 2
                )
                es = self._client.place_entry_stop_bracket(
                    symbol=symbol, quantity=total_quantity,
                    limit_price=entry_price, stop_loss_price=stop_loss,
                    trail_amount=trail_amount,
                )
                es_ids = es.get("order_ids", [])
                # Persist as the T2 leg with broker_order_ids laid out [entry, tp=None, stop]
                # so the bh_swing stop-manager reads the stop at its usual index.
                entry_id = es_ids[0] if len(es_ids) > 0 else None
                stop_id = es_ids[1] if len(es_ids) > 1 else None
                results.append(OrderResult(
                    symbol=symbol, strategy=strategy, quantity=total_quantity,
                    entry_price=entry_price, stop_loss_price=stop_loss,
                    take_profit_price=0.0,
                    order_ids=es_ids,
                    status=es.get("status", "error"), error=es.get("error"),
                    idea_id=cand_idea_id,
                    t2_order_ids=[entry_id, None, stop_id],
                    t2_qty=total_quantity, t1_target=0.0,
                ))
                continue

            if t1_qty <= 0:
                # Too small to split into two viable legs: place a single T2 order.
                order_result = self._client.place_bracket_order(
                    symbol=symbol, quantity=t2_qty, limit_price=entry_price,
                    take_profit_price=take_profit, stop_loss_price=stop_loss,
                )
                t2_ids = order_result.get("order_ids", [])
                results.append(OrderResult(
                    symbol=symbol, strategy=strategy, quantity=t2_qty,
                    entry_price=entry_price, stop_loss_price=stop_loss,
                    take_profit_price=take_profit,
                    order_ids=t2_ids,
                    status=order_result.get("status", "error"),
                    error=order_result.get("error"),
                    idea_id=cand_idea_id,
                    t2_order_ids=t2_ids, t2_qty=t2_qty,
                    t1_target=t1_target,
                ))
                continue

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

    def _position_sizes(self, selected: List[dict]) -> Dict[int, float]:
        """Target dollars per selected candidate, keyed by ``id(candidate)``.

        Conviction-weighted: the pot (``len(selected) * base``, where
        ``base = total_investment / max_positions``) is exactly what flat sizing
        would deploy for this many slots, split proportional to each sleeve's
        validated edge (``edge_weight``). Total capital is therefore unchanged from
        flat sizing — only its DISTRIBUTION tilts toward higher-edge sleeves. Each
        position is capped at ``max_position_mult * base`` to bound single-name
        concentration (excess left undeployed).

        Falls back to flat (``base`` each) when conviction sizing is off or every
        selected sleeve has zero validated edge. A zero-weight sleeve in an
        otherwise-validated set (e.g. the unregistered Connors) sizes to $0 — it
        held a leftover slot but earns no capital, so that capital flows to the
        validated names.
        """
        base = self._config.total_investment / self._config.max_positions
        flat = {id(c): base for c in selected}
        if not getattr(self._config, "conviction_sizing", True) or not selected:
            return flat
        wmap = self._edge_weight_map()
        weights = [wmap.get(c.get("strategy", ""), 0.0) for c in selected]
        total_w = sum(weights)
        if total_w <= 0:
            return flat  # all-unvalidated → flat-equal
        pot = len(selected) * base
        cap = getattr(self._config, "max_position_mult", 2.5) * base
        return {id(c): min(pot * w / total_w, cap) for c, w in zip(selected, weights)}

    def preview_fractional_plan(self, candidates: List[dict]) -> Dict[int, Dict[str, float]]:
        """Preview the bot's intended sizing for the prediction report — FRACTIONAL.

        Runs the SAME selection + conviction sizing the live trader uses, but
        broker-free and assuming an empty book (all ``max_positions`` slots open) —
        the deterministic "what the bot intends today" view. Tracking-only sleeves
        are excluded exactly as in live submission. Shares are the exact
        ``dollars / entry`` with NO flooring: the report shows the unfloored ideal,
        while live execution floors to whole shares (``_split_quantity``).

        Returns ``{id(candidate): {'shares': float, 'dollars': float}}`` for the
        selected candidates only (others would not get a slot today).
        """
        from bluehorseshoe.analysis.strategy_registry import get_all_strategies
        no_trade = {s.display_name for s in get_all_strategies() if not s.paper_tradeable}
        eligible = [c for c in candidates if c.get("strategy") not in no_trade]
        selected = self._select_with_reservation(eligible, set(), self._config.max_positions)
        dollars = self._position_sizes(selected)
        plan: Dict[int, Dict[str, float]] = {}
        for c in selected:
            d = dollars.get(id(c), 0.0)
            px = c.get("close", 0) or 0
            if d > 0 and px > 0:
                plan[id(c)] = {"shares": round(d / px, 4), "dollars": round(d, 2)}
        return plan

    def _split_quantity(self, dollars: float, entry_price: float) -> Tuple[float, float, float]:
        """Return ``(total, t1, t2)`` share quantities for a dollar target.

        Fractional mode (default): exact ``dollars / price`` rounded to
        ``fractional_precision``, split in half — no rounding leak. Below
        ``min_order_value`` notional → ``(0,0,0)`` (skip); below 2x that → a single
        (T2-only) leg, signalled by ``t1 == 0`` (too small to split into two viable
        broker orders). Whole-share mode (``fractional_shares=False``): the legacy
        floor with its ">=2 to split, >=1 to trade" rules.
        """
        if entry_price <= 0:
            return 0.0, 0.0, 0.0
        if not getattr(self._config, "fractional_shares", True):
            total = math.floor(dollars / entry_price)
            if total < 1:
                return 0.0, 0.0, 0.0
            if total < 2:
                return 1.0, 0.0, 1.0          # single leg (can't split 1 share)
            t1 = total // 2
            return float(total), float(t1), float(total - t1)
        prec = getattr(self._config, "fractional_precision", 4)
        min_val = getattr(self._config, "min_order_value", 1.0)
        total = round(dollars / entry_price, prec)
        if total * entry_price < min_val:
            return 0.0, 0.0, 0.0              # too small to place at all
        if total * entry_price < 2 * min_val:
            return total, 0.0, total          # too small to split → single leg
        t1 = round(total / 2, prec)
        return total, t1, round(total - t1, prec)

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
            # Secondary key: support `strength` — the validated within-sleeve tiebreak
            # (bake-off: only key that monotonically sorts per-trade R). Ties on edge-
            # weighted score now go to the higher-quality level, not alphabetically.
            return sorted(
                eligible,
                key=lambda c: (c.get("score", 0.0) * wmap.get(c.get("strategy", ""), 0.0),
                               c.get("strength", 0.0)),
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

        # Sort each pool by (score, support strength) so the reserved-slot slices below
        # take the highest-quality levels within a sleeve, not whatever order they arrived.
        def _key(c):
            return (c.get("score", 0.0), c.get("strength", 0.0))
        deep_cands = sorted([c for c in eligible if c.get("strategy") == deepos_display],
                            key=_key, reverse=True)
        legacy_cands = sorted([c for c in eligible if c.get("strategy") != deepos_display],
                              key=_key, reverse=True)

        # Reserved (guaranteed) picks first; if the global cap binds, highest score wins.
        guaranteed = sorted(
            deep_cands[:deep_slots] + legacy_cands[:legacy_slots],
            key=_key, reverse=True,
        )
        selected = guaranteed[:slots_available]

        # Spillover: fill remaining global slots from leftover candidates by score.
        if len(selected) < slots_available:
            leftover = sorted(
                deep_cands[deep_slots:] + legacy_cands[legacy_slots:],
                key=_key, reverse=True,
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
        """Check that prices are positive and logically consistent.

        ``take_profit <= 0`` is the explicit "no take-profit" signal (the range_support
        sleeve), validated as entry + stop only; a positive take_profit must sit above entry.
        """
        if entry <= 0 or stop_loss <= 0:
            return False
        if stop_loss >= entry:
            return False
        if take_profit > 0 and take_profit <= entry:   # only enforce ordering when a TP exists
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
            if r.status not in ("submitted", "partial"):
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
