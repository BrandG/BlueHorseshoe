"""
tiingo_news.py

Fetch news headlines from Tiingo, score them with VADER sentiment,
and store results in MongoDB for comparison with Alpha Vantage sentiment.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, date, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
from ratelimit import limits, sleep_and_retry
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from bluehorseshoe.core.config import get_settings

logger = logging.getLogger(__name__)

# Module-level VADER instance (stateless, thread-safe)
_vader = SentimentIntensityAnalyzer()

# ---------------------------------------------------------------------------
# Rate-limited fetch
# ---------------------------------------------------------------------------

TIINGO_NEWS_URL = "https://api.tiingo.com/tiingo/news"


def _get_tiingo_cps() -> int:
    return get_settings().tiingo_cps or 5


@sleep_and_retry
@limits(calls=5, period=1)
def fetch_tiingo_news(
    tickers: str | List[str],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    Fetch news articles from Tiingo news API.

    Args:
        tickers: Comma-separated string or list of ticker symbols.
        start_date: ISO date string (YYYY-MM-DD). Defaults to 7 days ago.
        end_date: ISO date string (YYYY-MM-DD). Defaults to today.
        limit: Max articles to return (Tiingo default 100, we default 50).

    Returns:
        List of article dicts. Empty list on failure or missing API key.
    """
    settings = get_settings()
    api_key = settings.tiingo_api_key
    if not api_key:
        logger.debug("TIINGO_API_KEY not set — skipping Tiingo news fetch")
        return []

    if isinstance(tickers, list):
        tickers = ",".join(tickers)

    if not start_date:
        start_date = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    if not end_date:
        end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    params = {
        "tickers": tickers,
        "startDate": start_date,
        "endDate": end_date,
        "limit": limit,
        "token": api_key,
    }

    try:
        resp = requests.get(TIINGO_NEWS_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        logger.warning("Tiingo news returned non-list response for %s", tickers)
        return []
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Tiingo news fetch failed for %s: %s", tickers, exc)
        return []


# ---------------------------------------------------------------------------
# VADER scoring
# ---------------------------------------------------------------------------

def score_article_vader(title: str) -> float:
    """Return VADER compound score for a single title. Range [-1, +1]."""
    if not title:
        return 0.0
    return _vader.polarity_scores(title)["compound"]


def score_articles(articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Add ``vader_score`` key to each article dict (in-place + returned)."""
    for art in articles:
        art["vader_score"] = score_article_vader(art.get("title", ""))
    return articles


# ---------------------------------------------------------------------------
# MongoDB persistence
# ---------------------------------------------------------------------------

def upsert_tiingo_news_to_mongo(
    symbol: str, articles: List[Dict[str, Any]], database=None
) -> None:
    """
    Store scored Tiingo articles in ``symbol_news_tiingo`` collection.

    Document shape: ``{symbol, articles[], last_updated}``
    """
    if database is None:
        raise ValueError("database parameter is required for upsert_tiingo_news_to_mongo")

    sym = symbol.upper().strip()
    col = database["symbol_news_tiingo"]

    doc = {
        "symbol": sym,
        "articles": articles,
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }
    col.update_one({"symbol": sym}, {"$set": doc}, upsert=True)


# ---------------------------------------------------------------------------
# Sentiment score from stored Tiingo data
# ---------------------------------------------------------------------------

def _normalize_target_date(target_date: str | date) -> Optional[datetime]:
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


def get_tiingo_sentiment_score_with_count(
    symbol: str, target_date: str | date, database=None
) -> Tuple[float, int]:
    """
    7-day lookback average of stored VADER scores for *symbol*.

    Returns:
        ``(average_score, article_count)`` — matches AV signature.
    """
    if database is None:
        raise ValueError(
            "database parameter is required for get_tiingo_sentiment_score_with_count"
        )

    sym = symbol.upper().strip()
    target_dt = _normalize_target_date(target_date)
    if not target_dt:
        return 0.0, 0

    doc = database["symbol_news_tiingo"].find_one({"symbol": sym}, {"_id": 0})
    if not doc:
        return 0.0, 0

    articles = doc.get("articles", [])
    scores: List[float] = []

    for art in articles:
        pub_str = art.get("publishedDate", "")
        if not pub_str:
            continue
        try:
            pub_dt = datetime.fromisoformat(pub_str)
            # Strip tzinfo for naive comparison
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
