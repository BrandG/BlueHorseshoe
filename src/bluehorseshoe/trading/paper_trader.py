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
from typing import List, Optional

from pymongo.database import Database

from bluehorseshoe.data.ibkr_client import IBKRClient

logger = logging.getLogger(__name__)


@dataclass
class PaperTradeConfig:
    """Configuration for paper trading."""
    total_investment: float = 10000.0
    max_positions: int = 10
    logs_path: str = "/workspaces/BlueHorseshoe/src/logs"


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
        self._collection = database["paper_trades"] if database is not None else None

    def execute(
        self, candidates: List[dict], target_date: str
    ) -> List[OrderResult]:
        """
        Submit bracket orders for top N candidates.

        Args:
            candidates: Sorted list of candidate dicts from swing_predict().
                        Each has: symbol, strategy, close (entry), stop_loss, target
            target_date: Date string (YYYY-MM-DD) for logging and duplicate detection.

        Returns:
            List of OrderResult for each candidate processed.
        """
        top = candidates[: self._config.max_positions]
        per_position = self._config.total_investment / self._config.max_positions

        results: List[OrderResult] = []

        for cand in top:
            symbol = cand.get("symbol", "")
            strategy = cand.get("strategy", "unknown")
            entry_price = cand.get("close", 0)
            stop_loss = cand.get("stop_loss", 0)
            take_profit = cand.get("target", 0)

            result = OrderResult(
                symbol=symbol,
                strategy=strategy,
                entry_price=entry_price,
                stop_loss_price=stop_loss,
                take_profit_price=take_profit,
            )

            # Validate prices
            if not self._validate_prices(entry_price, stop_loss, take_profit):
                result.status = "skipped"
                result.error = "invalid prices"
                results.append(result)
                continue

            # Check duplicates
            if self._is_duplicate(symbol, target_date, strategy):
                result.status = "skipped"
                result.error = "duplicate"
                results.append(result)
                continue

            # Calculate position size
            quantity = math.floor(per_position / entry_price)
            if quantity < 1:
                result.status = "skipped"
                result.error = "insufficient capital for 1 share"
                results.append(result)
                continue
            result.quantity = quantity

            # Place bracket order
            order_result = self._client.place_bracket_order(
                symbol=symbol,
                quantity=quantity,
                limit_price=entry_price,
                take_profit_price=take_profit,
                stop_loss_price=stop_loss,
            )

            result.order_ids = order_result.get("order_ids", [])
            result.status = order_result.get("status", "error")
            result.error = order_result.get("error")
            results.append(result)

        # Log results
        self._log_csv(results, target_date)
        self._log_mongo(results, target_date)

        return results

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
