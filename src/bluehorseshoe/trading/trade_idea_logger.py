"""
Trade idea logger — captures the top-N actionable candidates from each
prediction run into the trade_ideas MongoDB collection.

This is distinct from journal_signals (which captures ALL signals).
trade_ideas captures only the subset you intend to trade.
"""
import logging
import math
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from pymongo.database import Database

from bluehorseshoe.trading.trade_models import (
    TradeIdea,
    make_idea_id,
    normalize_strategy,
)

logger = logging.getLogger(__name__)


class TradeIdeaLogger:
    """Logs actionable trade ideas to MongoDB."""

    def __init__(self, database: Database):
        self._db = database
        self._collection = database["trade_ideas"]
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        """Create indexes if they don't already exist."""
        try:
            self._collection.create_index(
                [("idea_id", 1)], unique=True, name="ux_idea_id"
            )
            self._collection.create_index(
                [("batch_date", 1)], name="ix_batch_date"
            )
        except Exception as e:
            logger.warning("Failed to create trade_ideas indexes: %s", e)

    def log_ideas(
        self,
        candidates: List[dict],
        batch_date: str,
        max_positions: int = 10,
        total_investment: float = 10000.0,
    ) -> Tuple[int, Dict[Tuple[str, str], str]]:
        """
        Log top-N candidates as trade ideas.

        Args:
            candidates: Sorted candidate dicts from swing_predict().
            batch_date: Prediction date (YYYY-MM-DD).
            max_positions: Number of top candidates to log.
            total_investment: Total capital for position sizing.

        Returns:
            Tuple of (count logged, idea_lookup dict mapping
            (symbol, strategy_display) -> idea_id).
        """
        if not candidates:
            return 0, {}

        top = candidates[:max_positions]
        per_position = total_investment / max_positions if max_positions > 0 else 0
        logged = 0
        idea_lookup: Dict[Tuple[str, str], str] = {}

        for rank, cand in enumerate(top, start=1):
            try:
                symbol = cand.get("symbol", "")
                strategy_display = cand.get("strategy", "unknown")
                strategy = normalize_strategy(strategy_display)
                entry_price = cand.get("close", 0.0)

                if not symbol or entry_price <= 0:
                    continue

                idea_id = make_idea_id(batch_date, symbol, strategy)

                # Position sizing — same formula as PaperTrader
                shares = math.floor(per_position / entry_price) if entry_price > 0 else 0
                dollars = shares * entry_price

                # Parse components from reasons list (["ADX=8.5", ...])
                components = {}
                for reason in cand.get("reasons", []):
                    if "=" in reason:
                        key, val = reason.split("=", 1)
                        try:
                            components[key] = float(val)
                        except ValueError:
                            components[key] = 0.0

                # Compute risk/reward ratio
                stop = cand.get("stop_loss", 0.0)
                target = cand.get("target", 0.0)
                risk = entry_price - stop if stop > 0 else 0
                reward = target - entry_price if target > 0 else 0
                rr_ratio = reward / risk if risk > 0 else 0.0

                idea = TradeIdea(
                    idea_id=idea_id,
                    batch_date=batch_date,
                    symbol=symbol,
                    strategy=strategy,
                    rank=rank,
                    composite_score=cand.get("score", 0.0),
                    ml_win_probability=cand.get("ml_prob", 0.0),
                    signal_strength=self._infer_signal_strength(cand.get("score", 0.0)),
                    entry_price=entry_price,
                    stop_loss=stop,
                    take_profit_t1=cand.get("t1_target", entry_price * 1.02),
                    take_profit_t2=target,
                    risk_reward_ratio=round(rr_ratio, 2),
                    position_size_shares=shares,
                    position_size_dollars=round(dollars, 2),
                    components=components,
                    sentiment=cand.get("sentiment_composite", cand.get("sentiment", 0.0)),
                )

                doc = idea.to_doc()
                self._collection.update_one(
                    {"idea_id": idea_id},
                    {"$set": doc},
                    upsert=True,
                )
                idea_lookup[(symbol, strategy_display)] = idea_id
                logged += 1

            except Exception as e:
                logger.error(
                    "Failed to log trade idea for %s: %s",
                    cand.get("symbol", "?"),
                    e,
                )

        if logged > 0:
            logger.info("Logged %d trade ideas for %s", logged, batch_date)

        return logged, idea_lookup

    def get_ideas(self, batch_date: str) -> List[dict]:
        """Retrieve all trade ideas for a specific date, sorted by rank."""
        return list(
            self._collection.find(
                {"batch_date": batch_date},
                {"_id": 0},
            ).sort("rank", 1)
        )

    def get_idea(self, idea_id: str) -> Optional[dict]:
        """Retrieve a single trade idea by ID."""
        return self._collection.find_one({"idea_id": idea_id}, {"_id": 0})

    def get_unmatched_ideas(self, batch_date: str) -> List[dict]:
        """Get ideas that don't yet have corresponding orders."""
        # An idea is unmatched if no trade_orders doc references its idea_id
        orders_col = self._db["trade_orders"]
        matched_ids = orders_col.distinct("idea_id", {"idea_id": {"$ne": None}})
        return list(
            self._collection.find(
                {"batch_date": batch_date, "idea_id": {"$nin": matched_ids}},
                {"_id": 0},
            ).sort("rank", 1)
        )

    @staticmethod
    def _infer_signal_strength(score: float) -> str:
        """Infer signal strength from composite score."""
        if score >= 15.0:
            return "HIGH"
        if score >= 8.0:
            return "MEDIUM"
        return "LOW"
