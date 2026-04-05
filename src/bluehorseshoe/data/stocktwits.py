"""
stocktwits.py

Fetch per-symbol message streams from StockTwits, derive a bull/bear ratio
score from user-tagged sentiments, and store results in MongoDB.
No API key required — uses the free public endpoint.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import requests
from ratelimit import limits, sleep_and_retry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate-limited fetch
# ---------------------------------------------------------------------------

STOCKTWITS_STREAM_URL = "https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


@sleep_and_retry
@limits(calls=3, period=1)
def fetch_stocktwits_messages(symbol: str, limit: int = 30) -> List[Dict[str, Any]]:
    """
    Fetch the most recent messages for *symbol* from StockTwits.

    No authentication required.  Rate-limited to ~3 req/s (180 req/min)
    which stays safely under the 200 req/hour public cap.

    Returns:
        List of message dicts from ``response["messages"]``.
        Empty list on failure, missing data, or unknown symbol.
    """
    url = STOCKTWITS_STREAM_URL.format(symbol=symbol.upper().strip())
    params = {"limit": limit}

    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        messages = data.get("messages", [])
        if isinstance(messages, list):
            return messages
        logger.warning("StockTwits returned non-list messages for %s", symbol)
        return []
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("StockTwits fetch failed for %s: %s", symbol, exc)
        return []


# ---------------------------------------------------------------------------
# Scoring — ratio of bullish vs bearish tags
# ---------------------------------------------------------------------------

def score_stocktwits_messages(
    messages: List[Dict[str, Any]],
) -> Tuple[float, int, int, int]:
    """
    Count Bullish / Bearish user-tags and compute a ratio score.

    Each message may have ``entities.sentiment.basic`` set to
    ``"Bullish"`` or ``"Bearish"``, or ``entities`` may be ``None``.

    Returns:
        ``(score, bullish_count, bearish_count, total_tagged)``
        where ``score = (bull - bear) / (bull + bear)``  in [-1, +1],
        or 0.0 when no tagged messages exist.
    """
    bullish = 0
    bearish = 0

    for msg in messages:
        entities = msg.get("entities")
        if entities is None:
            continue
        sentiment = entities.get("sentiment")
        if sentiment is None:
            continue
        basic = sentiment.get("basic")
        if basic == "Bullish":
            bullish += 1
        elif basic == "Bearish":
            bearish += 1

    total_tagged = bullish + bearish
    if total_tagged == 0:
        return 0.0, 0, 0, 0

    score = (bullish - bearish) / total_tagged
    return score, bullish, bearish, total_tagged


# ---------------------------------------------------------------------------
# MongoDB persistence
# ---------------------------------------------------------------------------

def upsert_stocktwits_to_mongo(
    symbol: str,
    messages: List[Dict[str, Any]],
    score_data: Tuple[float, int, int, int],
    database=None,
) -> None:
    """
    Store StockTwits messages and score in ``symbol_news_stocktwits``.

    Document shape::

        {symbol, messages[], score, bullish, bearish, total_tagged, last_updated}
    """
    if database is None:
        raise ValueError("database parameter is required for upsert_stocktwits_to_mongo")

    sym = symbol.upper().strip()
    score, bullish, bearish, total_tagged = score_data
    col = database["symbol_news_stocktwits"]

    doc = {
        "symbol": sym,
        "messages": messages,
        "score": score,
        "bullish": bullish,
        "bearish": bearish,
        "total_tagged": total_tagged,
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }
    col.update_one({"symbol": sym}, {"$set": doc}, upsert=True)


# ---------------------------------------------------------------------------
# Read stored score (matches AV / Tiingo signature)
# ---------------------------------------------------------------------------

def get_stocktwits_sentiment_score_with_count(
    symbol: str, target_date, database=None
) -> Tuple[float, int]:
    """
    Look up stored StockTwits sentiment for *symbol*.

    ``target_date`` is accepted for API-signature parity with AV/Tiingo
    but is not used for filtering (StockTwits only returns the latest 30
    messages, not historical data).

    Returns:
        ``(score, total_tagged)`` — 0.0/0 when no data is stored.
    """
    if database is None:
        raise ValueError(
            "database parameter is required for get_stocktwits_sentiment_score_with_count"
        )

    sym = symbol.upper().strip()
    doc = database["symbol_news_stocktwits"].find_one({"symbol": sym}, {"_id": 0})
    if not doc:
        return 0.0, 0

    return doc.get("score", 0.0), doc.get("total_tagged", 0)
