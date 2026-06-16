"""Corporate-action detection for the equity (Gordon) candidate pipeline.

Catches names that have stopped behaving like normal tradeable equities because
they are the TARGET of a pending acquisition. Once a cash deal is announced the
stock gaps to just under the offer price and then trades dead-flat: upside is
capped at the cash consideration, so a trend/swing entry there is structurally
bad (capped upside, only deal-break downside) and the broker may freeze trading
before close. KW/Kennedy-Wilson (cash take-private at $10.90) was the motivating
case — bought at $10.93 into a $10.90 deal is a guaranteed small loss with the
position frozen until the merger closes.

Two complementary detectors, deliberately surfaced as an ANNOTATION first rather
than a hard skip (a heuristic must be auditable on live runs before it suppresses
candidates):

  * Layer B — ``liquidity.is_merger_pinned``: the price signature (volatility
    collapse vs the name's own baseline + a tight absolute band). Fires during
    the weeks after announcement, while the pre-pin baseline is still in window.
  * Layer C — ``scan_news_for_merger`` (here): merger/acquisition-target language
    in the already-ingested AlphaVantage news feed. Catches standing deals that
    have been pinned long enough for the price-collapse signal to fade.

Together: B catches the fresh transition, C catches the long-standing deal.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from bluehorseshoe.analysis.liquidity import is_merger_pinned
from bluehorseshoe.core.symbols import get_news_sentiment_from_mongo

logger = logging.getLogger(__name__)

# Acquisition-TARGET language. Phrases, not bare words, so we don't match the
# ACQUIRER side ("X agrees to acquire Y" doesn't pin X) or generic M&A chatter.
MERGER_KEYWORDS: tuple[str, ...] = (
    "to be acquired",
    "agreed to be acquired",
    "agreement to be acquired",
    "definitive agreement",
    "merger agreement",
    "to go private",
    "take private",
    "take-private",
    "go-private",
    "per share in cash",
    "all-cash transaction",
    "all cash transaction",
    "cash merger",
    "tender offer",
    "buyout",
)


def _parse_relevance(item: Dict[str, Any], symbol: str) -> float:
    """AlphaVantage per-ticker relevance for ``symbol`` in a news item (0.0 if absent)."""
    sym = symbol.upper().strip()
    for ts in item.get("ticker_sentiment", []) or []:
        if str(ts.get("ticker", "")).upper().strip() == sym:
            try:
                return float(ts.get("relevance_score", 0.0))
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _parse_time(item: Dict[str, Any]) -> Optional[datetime]:
    """Parse AV ``time_published`` (``YYYYMMDDTHHMMSS``); None when missing/unparseable."""
    raw = item.get("time_published")
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw), "%Y%m%dT%H%M%S")
    except (TypeError, ValueError):
        return None


def scan_news_for_merger(
    feed: Sequence[Dict[str, Any]],
    symbol: str,
    lookback_days: int = 270,
    min_relevance: float = 0.4,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Scan an AV NEWS_SENTIMENT feed for acquisition-TARGET language about ``symbol``.

    A headline counts as a hit when it carries merger language AND is genuinely
    about this ticker: a keyword in the *title* is strong evidence on its own; a
    summary-only match additionally requires AV relevance >= ``min_relevance`` so
    passing mentions don't trip the flag. ``lookback_days`` defaults to ~9 months
    because a deal stays relevant from announcement until close (KW: Feb→June),
    and a *completed* deal delists the ticker (caught upstream by the dead-series
    gate), so a generous window can't resurface stale closed deals.

    Returns ``{"hit": bool, "headlines": [..], "latest": "YYYY-MM-DD"|None}``.
    """
    now = now or datetime.now()
    cutoff = now - timedelta(days=lookback_days)
    headlines: List[str] = []
    latest: Optional[datetime] = None

    for item in feed or []:
        title = str(item.get("title", "") or "")
        summary = str(item.get("summary", "") or "")
        in_title = any(k in title.lower() for k in MERGER_KEYWORDS)
        in_summary = any(k in summary.lower() for k in MERGER_KEYWORDS)
        if not (in_title or in_summary):
            continue
        # summary-only matches must clear the relevance bar
        if not in_title and _parse_relevance(item, symbol) < min_relevance:
            continue
        pub = _parse_time(item)
        if pub is not None and pub < cutoff:
            continue
        headlines.append(title.strip() or "(untitled merger headline)")
        if pub is not None and (latest is None or pub > latest):
            latest = pub

    return {
        "hit": bool(headlines),
        "headlines": headlines[:5],
        "latest": latest.strftime("%Y-%m-%d") if latest else None,
    }


@dataclass
class CorporateActionFlag:
    """Combined price (B) + news (C) corporate-action annotation for one symbol."""

    symbol: str
    pinned: bool = False
    news_merger: bool = False
    headlines: List[str] = field(default_factory=list)
    news_latest: Optional[str] = None

    @property
    def flagged(self) -> bool:
        return self.pinned or self.news_merger

    @property
    def reason(self) -> str:
        bits: List[str] = []
        if self.pinned:
            bits.append("price pinned (vol-collapse + tight band)")
        if self.news_merger:
            latest = f", latest {self.news_latest}" if self.news_latest else ""
            bits.append(f"{len(self.headlines)} merger headline(s){latest}")
        return "; ".join(bits) or "none"

    def to_dict(self) -> Dict[str, Any]:
        """Picklable annotation payload to ride along on the preload result dict."""
        return {
            "flagged": self.flagged,
            "pinned": self.pinned,
            "news_merger": self.news_merger,
            "headlines": self.headlines,
            "news_latest": self.news_latest,
            "reason": self.reason,
        }


def assess_corporate_action(
    symbol: str,
    df: pd.DataFrame,
    database=None,
    now: Optional[datetime] = None,
) -> CorporateActionFlag:
    """Combine the price-pin (B) and news (C) detectors into one annotation.

    Fail-open: any detector error is logged and treated as "no signal" — a
    corporate-action heuristic must never be the reason a tradeable name is
    dropped or a prediction run crashes. ``database`` may be None (price-only).
    """
    flag = CorporateActionFlag(symbol=symbol.upper().strip())
    try:
        flag.pinned = is_merger_pinned(df)
    except Exception:  # pylint: disable=broad-exception-caught  # fail-open
        logger.exception("is_merger_pinned failed for %s", symbol)
    if database is not None:
        try:
            feed = get_news_sentiment_from_mongo(symbol, database=database)
            news = scan_news_for_merger(feed, symbol, now=now)
            flag.news_merger = bool(news["hit"])
            flag.headlines = list(news["headlines"])
            flag.news_latest = news["latest"]
        except Exception:  # pylint: disable=broad-exception-caught  # fail-open
            logger.exception("merger news scan failed for %s", symbol)
    return flag
