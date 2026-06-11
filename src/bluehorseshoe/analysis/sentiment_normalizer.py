"""
sentiment_normalizer.py

Z-score normalizes sentiment scores from multiple sources against their
historical distributions, then produces a composite via tanh squashing.
"""
import logging
import math
from typing import Dict, Optional

from pymongo.database import Database

# Minimum number of historical data points per source before z-score
# normalization is applied.  Below this threshold the raw score is returned.
MIN_HISTORY_COUNT = 30

# Maps source names (as stored in sentiment_snapshots) to the candidate
# dict keys that hold the raw score for that source.
SOURCE_KEY_MAP = {
    "alphavantage": "sentiment",
    "tiingo": "sentiment_tiingo",
    "stocktwits": "sentiment_stocktwits",
    "finviz": "sentiment_finviz",
}


class SentimentNormalizer:
    """Normalize per-source sentiment scores via z-score + tanh."""

    def __init__(self, database: Database):
        if database is None:
            raise ValueError("SentimentNormalizer requires a database connection")
        self.database = database
        # {source: {"mean": float, "std": float, "count": int}}
        self.stats: Dict[str, Dict[str, float]] = {}

    # ------------------------------------------------------------------
    # Load historical stats
    # ------------------------------------------------------------------
    def load_source_stats(self, limit: int = 90) -> None:
        """Compute per-source mean/std/count from recent sentiment_snapshots."""
        try:
            pipeline = [
                # pit_unsafe rows were written by historical-date backtest/eval runs
                # (current feed values stamped onto old dates) - never use them
                {"$match": {"pit_unsafe": {"$ne": True}}},
                {"$sort": {"date": -1}},
                {"$limit": limit * 500},  # generous upper bound
                {"$group": {
                    "_id": "$source",
                    "mean": {"$avg": "$score"},
                    "std": {"$stdDevPop": "$score"},
                    "count": {"$sum": 1},
                }},
            ]
            collection = self.database["sentiment_snapshots"]
            for doc in collection.aggregate(pipeline):
                source = doc["_id"]
                self.stats[source] = {
                    "mean": doc.get("mean", 0.0) or 0.0,
                    "std": doc.get("std", 0.0) or 0.0,
                    "count": doc.get("count", 0),
                }
            logging.info(
                "Loaded sentiment stats for %d sources: %s",
                len(self.stats),
                {s: f"n={v['count']}" for s, v in self.stats.items()},
            )
        except Exception:  # pylint: disable=broad-except
            logging.warning("Failed to load sentiment source stats (non-fatal)")
            self.stats = {}

    # ------------------------------------------------------------------
    # Normalize a single raw score
    # ------------------------------------------------------------------
    def normalize(self, raw_score: float, source: str) -> float:
        """Return tanh(z-score) for *raw_score*, or raw on fallback."""
        if raw_score == 0.0:
            return 0.0

        source_stats = self.stats.get(source)
        if source_stats is None:
            return raw_score
        if source_stats["count"] < MIN_HISTORY_COUNT:
            return raw_score
        if source_stats["std"] == 0.0:
            return raw_score

        z = (raw_score - source_stats["mean"]) / source_stats["std"]
        return math.tanh(z)

    # ------------------------------------------------------------------
    # Composite across all sources
    # ------------------------------------------------------------------
    def composite(self, candidate: dict) -> float:
        """Simple average of raw sentiment scores for non-zero sources."""
        values = []
        for _source, key in SOURCE_KEY_MAP.items():
            raw = candidate.get(key, 0.0)
            if raw == 0.0:
                continue
            values.append(raw)

        if not values:
            return 0.0
        return sum(values) / len(values)
