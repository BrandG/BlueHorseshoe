"""Tracking-only 48h news-sentiment annotation for DeepOS-family fires.

Research lineage (2026-06-11): deepos_news_gauntlet (48h variant) + deepos_news_depth_control —
among news-covered deep-oversold fires, the most-negative 48h sentiment tercile out-bounces the
rest in 17/18 depth buckets, and sentiment is uncorrelated with dislocation depth (the campaign's
second orthogonal conditioner after Altman-Z″). The nonbull year-split is too thin to lock it, so
these fields exist to accumulate the forward record: they freeze into ``journal_signals`` and the
hypothesis engine can split matured trades by arm. NOT a gate, NOT sizing — annotation only.

Point-in-time safety: annotation runs only on live predictions (target_date == latest market
date, same gate as sentiment-snapshot archiving). Historical/backtest runs must not stamp
current news onto old fires.
"""
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from bluehorseshoe.core.symbols import (
    fetch_news_sentiment_from_net,
    upsert_news_sentiment_to_mongo,
)

logger = logging.getLogger(__name__)

# Frozen research parameters — keep identical to deepos_news_depth_control.py.
REL_MIN = 0.2          # drop passing mentions (AV relevance_score < 0.2)
LOOKBACK_DAYS = 2      # acute window: [signal_date - 2d, signal_date] inclusive
SQ_LOW_CUT = 0.030     # q33 of covered nonbull fires 2022-03..2026-06 (depth-control run)
MAX_SYMBOLS = 200      # capitulation-day guard on per-symbol AV fetches

# DeepOS-family sleeves whose fires get annotated (live + HA tier).
SCORE_KEYS = ("deep_os_score", "deep_os_ha_score")


def compute_news_48h(
    feed: Optional[List[Dict[str, Any]]],
    symbol: str,
    target_date: str,
) -> Tuple[Optional[float], int]:
    """Relevance-weighted mean ticker sentiment over the acute pre-fire window.

    Mirrors the research harness: articles published on the LOOKBACK_DAYS calendar
    days up to and including the signal date, this ticker's sentiment entry only,
    relevance >= REL_MIN, weighted by relevance. Returns (mean, count);
    (None, 0) when uncovered.
    """
    try:
        target = datetime.strptime(str(target_date)[:10], "%Y-%m-%d")
    except ValueError:
        return None, 0
    lo = (target - timedelta(days=LOOKBACK_DAYS)).strftime("%Y%m%d")
    hi = target.strftime("%Y%m%d")

    num = 0.0
    den = 0.0
    count = 0
    sym = symbol.upper()
    for item in feed or []:
        day = str(item.get("time_published", ""))[:8]
        if not lo <= day <= hi:
            continue
        for ts in item.get("ticker_sentiment", []):
            if ts.get("ticker") != sym:
                continue
            try:
                rel = float(ts.get("relevance_score", 0.0))
                score = float(ts.get("ticker_sentiment_score", 0.0))
            except (TypeError, ValueError):
                continue
            if rel >= REL_MIN:
                num += rel * score
                den += rel
                count += 1
    if count == 0 or den <= 0:
        return None, 0
    return num / den, count


def classify_arm(mean: Optional[float], count: int) -> str:
    """Research arm for forward evaluation: nocov / sq_low / rest."""
    if count == 0 or mean is None:
        return "nocov"
    return "sq_low" if mean <= SQ_LOW_CUT else "rest"


def annotate_deepos_results(
    valid_results: List[Dict[str, Any]],
    *,
    target_date: str,
    database,
    fetch=fetch_news_sentiment_from_net,
    max_symbols: int = MAX_SYMBOLS,
) -> int:
    """Attach news_48h_{mean,count,arm} to DeepOS-family fire rows in place.

    Fetches a fresh AV feed per fire symbol (rate-limited upstream) and refreshes
    the rolling ``symbol_news`` cache as a side benefit. A failed fetch leaves that
    row un-annotated (absent fields, never fabricated zeros). Returns the number of
    rows annotated. Caller is responsible for the live-run gate.
    """
    fire_rows = [
        r for r in valid_results
        if any(r.get(k, 0) > 0 for k in SCORE_KEYS)
    ]
    symbols = sorted({r["symbol"] for r in fire_rows})
    if not symbols:
        return 0
    if len(symbols) > max_symbols:
        # Capitulation-day guard: annotate the cap, but never silently — the dropped
        # tail is visible in the log and the un-annotated rows are distinguishable
        # from nocov (fields absent vs arm="nocov").
        logger.warning(
            "news annotation: %d fire symbols exceeds cap %d — annotating first %d, "
            "dropping %d", len(symbols), max_symbols, max_symbols,
            len(symbols) - max_symbols,
        )
        symbols = symbols[:max_symbols]
    keep = set(symbols)

    feats: Dict[str, Tuple[Optional[float], int]] = {}
    for symbol in symbols:
        try:
            news_data = fetch(symbol)
            upsert_news_sentiment_to_mongo(symbol, news_data, database=database)
            feats[symbol] = compute_news_48h(news_data.get("feed", []), symbol, target_date)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("news annotation: fetch failed for %s (%s) — row left "
                           "un-annotated", symbol, exc)

    annotated = 0
    for r in fire_rows:
        sym = r["symbol"]
        if sym not in keep or sym not in feats:
            continue
        mean, count = feats[sym]
        r["news_48h_mean"] = mean
        r["news_48h_count"] = count
        r["news_48h_arm"] = classify_arm(mean, count)
        annotated += 1
    logger.info(
        "news annotation: %d DeepOS-family rows annotated across %d symbols for %s",
        annotated, len(feats), target_date,
    )
    return annotated
