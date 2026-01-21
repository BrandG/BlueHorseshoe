"""
Module for managing trade scores in MongoDB.
"""
from typing import List, Dict, Any, Optional
from datetime import datetime
from pymongo import UpdateOne
from pymongo.database import Database
from .database import db

class ScoreManager:
    """
    Manages the 'trade_scores' collection.
    Allows saving, retrieving, and clearing scores without touching historical data.
    """

    def __init__(self, database: Optional[Database] = None, collection_name: str = "trade_scores"):
        """
        Initialize ScoreManager with database dependency.

        Args:
            database: MongoDB Database instance. If None, uses legacy global singleton.
            collection_name: Name of the collection to use for scores.
        """
        self.collection_name = collection_name
        if database is None:
            # Backward compatibility with global singleton
            self._db = db.get_db()
        else:
            self._db = database
        self.collection = self._db[self.collection_name]
        # Ensure index for performance and uniqueness
        self.collection.create_index([("symbol", 1), ("date", 1), ("strategy", 1)], unique=True)

    def save_scores(self, scores: List[Dict[str, Any]]):
        """
        Bulk upsert scores.
        Each score dict should have: symbol, date, score, strategy, version, and optional metadata.
        """
        if not scores:
            return

        operations = []
        for s in scores:
            filter_query = {
                "symbol": s["symbol"],
                "date": s["date"],
                "strategy": s.get("strategy", "baseline")
            }
            update_query = {
                "$set": {
                    "score": s["score"],
                    "version": s.get("version", "1.0"),
                    "metadata": s.get("metadata", {}),
                    "updated_at": datetime.utcnow()
                }
            }
            operations.append(UpdateOne(filter_query, update_query, upsert=True))

        if operations:
            self.collection.bulk_write(operations, ordered=False)

    def get_scores(self, date: str, strategy: str = "baseline", min_score: Optional[float] = None) -> List[Dict[str, Any]]:
        """
        Retrieve scores for a specific date and strategy.
        """
        query = {"date": date, "strategy": strategy}
        if min_score is not None:
            query["score"] = {"$gte": min_score}

        return list(self.collection.find(query).sort("score", -1))

    def clear_scores(self, strategy: str = None, version: str = None):
        """
        Clear scores for a specific strategy and/or version.
        Use with caution - mainly for rebuilds.
        """
        query = {}
        if strategy:
            query["strategy"] = strategy
        if version:
            query["version"] = version

        result = self.collection.delete_many(query)
        return result.deleted_count

# Global instance (deprecated - for backward compatibility only)
# New code should create ScoreManager with explicit database dependency
score_manager = ScoreManager()  # Uses legacy global db singleton
