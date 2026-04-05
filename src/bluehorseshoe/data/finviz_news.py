"""
finviz_news.py

Fetch per-symbol news headlines from Finviz, score them with VADER sentiment,
and store results in MongoDB.  No API key required — uses finvizfinance library.
"""

from __future__ import annotations

import logging
from datetime import datetime, date, timezone
from typing import Any, Dict, List, Optional, Tuple

from ratelimit import limits, sleep_and_retry
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

logger = logging.getLogger(__name__)

# Module-level VADER instance (stateless, thread-safe)
_vader = SentimentIntensityAnalyzer()


# ---------------------------------------------------------------------------
# Rate-limited fetch
# ---------------------------------------------------------------------------

@sleep_and_retry
@limits(calls=1, period=1)
def fetch_finviz_news(symbol: str) -> List[Dict[str, Any]]:
    """
    Fetch news headlines for *symbol* from Finviz via finvizfinance.

    Rate-limited to ~1 req/sec to be polite to Finviz servers.

    Returns:
        List of dicts with keys ``Date``, ``Title``, ``Link``, ``Source``.
        Empty list on failure or unknown symbol.
    """
    try:
        from finvizfinance.quote import finvizfinance  # pylint: disable=import-outside-toplevel

        stock = finvizfinance(symbol.upper().strip())
        df = stock.ticker_news()
        if df is None or df.empty:
            return []
        return df.to_dict("records")
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Finviz news fetch failed for %s: %s", symbol, exc)
        return []


# ---------------------------------------------------------------------------
# VADER scoring
# ---------------------------------------------------------------------------

def score_finviz_headlines(articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Add ``vader_score`` key to each article dict (in-place + returned)."""
    for art in articles:
        title = art.get("Title", "")
        if not title:
            art["vader_score"] = 0.0
        else:
            art["vader_score"] = _vader.polarity_scores(title)["compound"]
    return articles


# ---------------------------------------------------------------------------
# MongoDB persistence
# ---------------------------------------------------------------------------

def upsert_finviz_news_to_mongo(
    symbol: str, articles: List[Dict[str, Any]], database=None
) -> None:
    """
    Store scored Finviz articles in ``symbol_news_finviz`` collection.

    Document shape: ``{symbol, articles[], last_updated}``
    """
    if database is None:
        raise ValueError("database parameter is required for upsert_finviz_news_to_mongo")

    sym = symbol.upper().strip()
    col = database["symbol_news_finviz"]

    doc = {
        "symbol": sym,
        "articles": articles,
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }
    col.update_one({"symbol": sym}, {"$set": doc}, upsert=True)


# ---------------------------------------------------------------------------
# Sentiment score from stored Finviz data
# ---------------------------------------------------------------------------

def _normalize_target_date(target_date) -> Optional[datetime]:
    """Convert various date inputs to datetime."""
    if isinstance(target_date, str):
        try:
            return datetime.strptime(target_date, "%Y-%m-%d")
        except ValueError:
            return None
    if isinstance(target_date, datetime):
        return target_date
    if isinstance(target_date, date):
        return datetime.combine(target_date, datetime.min.time())
    return None


def get_finviz_sentiment_score_with_count(
    symbol: str, target_date, database=None
) -> Tuple[float, int]:
    """
    7-day lookback average of stored VADER scores for *symbol*.

    Returns:
        ``(average_score, article_count)`` — 0.0/0 when no data.
    """
    if database is None:
        raise ValueError(
            "database parameter is required for get_finviz_sentiment_score_with_count"
        )

    sym = symbol.upper().strip()
    target_dt = _normalize_target_date(target_date)
    if not target_dt:
        return 0.0, 0

    doc = database["symbol_news_finviz"].find_one({"symbol": sym}, {"_id": 0})
    if not doc:
        return 0.0, 0

    articles = doc.get("articles", [])
    scores: List[float] = []

    for art in articles:
        pub = art.get("Date")
        if not pub:
            continue
        try:
            if isinstance(pub, str):
                pub_dt = datetime.fromisoformat(pub)
            elif isinstance(pub, datetime):
                pub_dt = pub
            else:
                continue
            pub_dt = pub_dt.replace(tzinfo=None)
        except (ValueError, TypeError):
            continue

        delta = target_dt - pub_dt
        if 0 <= delta.days <= 7:
            vader = art.get("vader_score")
            if vader is not None:
                try:
                    scores.append(float(vader))
                except (ValueError, TypeError):
                    pass

    avg = sum(scores) / len(scores) if scores else 0.0
    return avg, len(scores)
