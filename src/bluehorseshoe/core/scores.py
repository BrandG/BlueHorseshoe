"""
Module for managing trade scores in MongoDB.
"""
from typing import List, Dict, Any, Optional
from datetime import datetime
from pymongo import UpdateOne
from .database import db

class ScoreManager:
    """
    Manages the 'trade_scores' collection.
    Allows saving, retrieving, and clearing scores without touching historical data.
    """

    def __init__(self, collection_name: str = "trade_scores"):
        self.collection_name = collection_name
        self._db = db.get_db()
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

# Global instance
score_manager = ScoreManager()
