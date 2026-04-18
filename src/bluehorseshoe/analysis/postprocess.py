"""
Post-processing helpers for prediction output.

These collaborators keep candidate shaping and sentiment enrichment out of
SwingTrader's main orchestration flow.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from bluehorseshoe.analysis.sentiment_normalizer import SentimentNormalizer
from bluehorseshoe.core.config import get_settings
from bluehorseshoe.core.symbols import (
    fetch_news_sentiment_from_net,
    get_sentiment_score_with_count,
    save_sentiment_snapshots,
    upsert_news_sentiment_to_mongo,
)
from bluehorseshoe.data.finviz_news import (
    fetch_finviz_news,
    get_finviz_sentiment_score_with_count,
    score_finviz_headlines,
    upsert_finviz_news_to_mongo,
)
from bluehorseshoe.data.stocktwits import (
    fetch_stocktwits_messages,
    get_stocktwits_sentiment_score_with_count,
    score_stocktwits_messages,
    upsert_stocktwits_to_mongo,
)
from bluehorseshoe.data.tiingo_news import (
    fetch_tiingo_news,
    get_tiingo_sentiment_score_with_count,
    score_articles,
    upsert_tiingo_news_to_mongo,
)


class CandidateAssembler:
    """Build report-ready candidate rows from raw strategy results."""

    def __init__(self, strategies):
        self.strategies = strategies

    def build_top_candidates(self, valid_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Return merged top candidates across configured strategies plus Connors."""
        candidates: List[Dict[str, Any]] = []
        for result in valid_results:
            candidates.extend(self._build_strategy_candidates(result))

        connors_candidates = self._build_connors_candidates(valid_results)

        strategy_candidates: List[Dict[str, Any]] = []
        for strategy in self.strategies:
            strat_top = sorted(
                [candidate for candidate in candidates if candidate["strategy"] == strategy.display_name],
                key=lambda candidate: candidate["score"],
                reverse=True,
            )[:25]
            strategy_candidates.extend(strat_top)

        return sorted(strategy_candidates + connors_candidates, key=lambda candidate: candidate["score"], reverse=True)

    def _build_strategy_candidates(self, result: Dict[str, Any]) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        for strategy in self.strategies:
            score = result.get(strategy.score_key, 0)
            if score <= 0:
                continue

            setup = result.get(strategy.setup_key, {})
            entry_price = setup.get("entry_price", 0)
            components = result.get(strategy.components_key, {})
            candidate = {
                "symbol": result["symbol"],
                "exchange": result.get("exchange", "Unknown"),
                "strategy": strategy.display_name,
                "score": score,
                "close": entry_price,
                "stop_loss": setup.get("stop_loss", 0),
                "t1_target": entry_price * 1.02 if entry_price > 0 else 0,
                "target": setup.get("take_profit", 0),
                "ml_prob": result.get(strategy.ml_prob_key, 0.0),
                "sentiment": result.get("sentiment", 0.0),
                "sentiment_tiingo": result.get("sentiment_tiingo", 0.0),
                "sentiment_stocktwits": result.get("sentiment_stocktwits", 0.0),
                "sentiment_finviz": result.get("sentiment_finviz", 0.0),
                "intraday_resistance": components.get("intraday_resistance"),
                "reasons": [
                    f"{key}={value:.1f}"
                    for key, value in components.items()
                    if key != "intraday_resistance" and value != 0
                ],
            }
            if result.get("connors_flag"):
                candidate["connors_flag"] = True
            candidates.append(candidate)
        return candidates

    def _build_connors_candidates(self, valid_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        connors_candidates: List[Dict[str, Any]] = []
        for result in valid_results:
            if not result.get("connors_flag"):
                continue

            best_setup = None
            best_score = 0
            best_ml_prob = 0.0
            for strategy in reversed(self.strategies):
                if result.get(strategy.score_key, 0) > 0:
                    best_setup = result.get(strategy.setup_key, {})
                    best_score = result[strategy.score_key]
                    best_ml_prob = result.get(strategy.ml_prob_key, 0.0)
            if not best_setup:
                continue

            entry_price = best_setup.get("entry_price", 0)
            connors_candidates.append({
                "symbol": result["symbol"],
                "exchange": result.get("exchange", "Unknown"),
                "strategy": "Connors",
                "score": best_score,
                "close": entry_price,
                "stop_loss": best_setup.get("stop_loss", 0),
                "t1_target": entry_price * 1.02 if entry_price > 0 else 0,
                "target": best_setup.get("take_profit", 0),
                "ml_prob": best_ml_prob,
                "sentiment": result.get("sentiment", 0.0),
                "sentiment_tiingo": result.get("sentiment_tiingo", 0.0),
                "sentiment_stocktwits": result.get("sentiment_stocktwits", 0.0),
                "sentiment_finviz": result.get("sentiment_finviz", 0.0),
                "connors_rsi2": result.get("connors_rsi2"),
                "connors_sma200": result.get("connors_sma200"),
                "reasons": [
                    f"RSI2={result.get('connors_rsi2', 0):.1f}",
                    f"SMA200={result.get('connors_sma200', 0):.1f}",
                ],
            })

        return sorted(connors_candidates, key=lambda candidate: candidate["score"], reverse=True)[:10]


class SentimentEnricher:
    """Refresh and attach sentiment data to report-ready candidates."""

    def __init__(self, database):
        self.database = database

    def enrich(
        self,
        candidates: List[Dict[str, Any]],
        *,
        target_date: str | None,
        market_health: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Refresh source sentiment, persist snapshots, and compute composite values."""
        unique_symbols = list({candidate["symbol"] for candidate in candidates})
        logging.info("Refreshing sentiment for %d unique symbols in top 50 candidates", len(unique_symbols))
        for symbol in unique_symbols:
            try:
                news_data = fetch_news_sentiment_from_net(symbol)
                upsert_news_sentiment_to_mongo(symbol, news_data, database=self.database)
            except Exception:  # pylint: disable=broad-except
                logging.warning("Failed to fetch sentiment for %s, keeping existing value", symbol)

        target_date_str = str(target_date)
        sentiment_snapshots = self._build_market_sentiment_snapshots(market_health, target_date_str)

        self._attach_alpha_vantage_sentiment(candidates, target_date, target_date_str, sentiment_snapshots)
        self._attach_tiingo_sentiment(candidates, unique_symbols, target_date, target_date_str, sentiment_snapshots)
        self._attach_stocktwits_sentiment(candidates, unique_symbols, target_date, target_date_str, sentiment_snapshots)
        self._attach_finviz_sentiment(candidates, unique_symbols, target_date, target_date_str, sentiment_snapshots)
        self._persist_snapshots(sentiment_snapshots, target_date_str)
        self._attach_composite_sentiment(candidates)

        return candidates

    def _build_market_sentiment_snapshots(self, market_health: Dict[str, Any], target_date_str: str) -> List[Dict[str, Any]]:
        snapshots: List[Dict[str, Any]] = []

        vix = market_health.get("details", {}).get("VIX")
        if vix:
            snapshots.append({
                "symbol": "$VIX",
                "date": target_date_str,
                "score": vix["close"],
                "article_count": 0,
                "source": "vix",
            })

        aaii = market_health.get("details", {}).get("AAII")
        if aaii:
            snapshots.append({
                "symbol": "$AAII",
                "date": target_date_str,
                "score": aaii["spread_normalized"],
                "article_count": 0,
                "source": "aaii",
            })

        cnn = market_health.get("details", {}).get("CNN")
        if cnn:
            snapshots.append({
                "symbol": "$CNN_FG",
                "date": target_date_str,
                "score": cnn["score"],
                "article_count": 0,
                "source": "cnn_fear_greed",
            })

        return snapshots

    def _attach_alpha_vantage_sentiment(self, candidates, target_date, target_date_str, sentiment_snapshots):
        sentiment_cache: Dict[str, tuple] = {}
        for candidate in candidates:
            symbol = candidate["symbol"]
            if symbol not in sentiment_cache:
                sentiment_cache[symbol] = get_sentiment_score_with_count(symbol, target_date, database=self.database)
                score, count = sentiment_cache[symbol]
                if score != 0.0:
                    sentiment_snapshots.append({
                        "symbol": symbol,
                        "date": target_date_str,
                        "score": score,
                        "article_count": count,
                        "source": "alphavantage",
                    })
            candidate["sentiment"] = sentiment_cache[symbol][0]

    def _attach_tiingo_sentiment(self, candidates, unique_symbols, target_date, target_date_str, sentiment_snapshots):
        tiingo_cache: Dict[str, tuple] = {}
        if get_settings().tiingo_api_key:
            logging.info("Fetching Tiingo news sentiment for %d symbols", len(unique_symbols))
            for symbol in unique_symbols:
                try:
                    articles = fetch_tiingo_news(symbol)
                    if articles:
                        score_articles(articles)
                        upsert_tiingo_news_to_mongo(symbol, articles, database=self.database)
                except Exception:  # pylint: disable=broad-except
                    logging.warning("Tiingo news fetch failed for %s (non-fatal)", symbol)

            for candidate in candidates:
                symbol = candidate["symbol"]
                if symbol not in tiingo_cache:
                    tiingo_cache[symbol] = get_tiingo_sentiment_score_with_count(symbol, target_date, database=self.database)
                    score, count = tiingo_cache[symbol]
                    if score != 0.0:
                        sentiment_snapshots.append({
                            "symbol": symbol,
                            "date": target_date_str,
                            "score": score,
                            "article_count": count,
                            "source": "tiingo",
                        })
                candidate["sentiment_tiingo"] = tiingo_cache[symbol][0]

    def _attach_stocktwits_sentiment(self, candidates, unique_symbols, target_date, target_date_str, sentiment_snapshots):
        stocktwits_cache: Dict[str, tuple] = {}
        logging.info("Fetching StockTwits sentiment for %d symbols", len(unique_symbols))
        for symbol in unique_symbols:
            try:
                messages = fetch_stocktwits_messages(symbol)
                if messages:
                    score_data = score_stocktwits_messages(messages)
                    upsert_stocktwits_to_mongo(symbol, messages, score_data, database=self.database)
            except Exception:  # pylint: disable=broad-except
                logging.warning("StockTwits fetch failed for %s (non-fatal)", symbol)

        for candidate in candidates:
            symbol = candidate["symbol"]
            if symbol not in stocktwits_cache:
                stocktwits_cache[symbol] = get_stocktwits_sentiment_score_with_count(symbol, target_date, database=self.database)
                score, count = stocktwits_cache[symbol]
                if score != 0.0:
                    sentiment_snapshots.append({
                        "symbol": symbol,
                        "date": target_date_str,
                        "score": score,
                        "article_count": count,
                        "source": "stocktwits",
                    })
            candidate["sentiment_stocktwits"] = stocktwits_cache[symbol][0]

    def _attach_finviz_sentiment(self, candidates, unique_symbols, target_date, target_date_str, sentiment_snapshots):
        finviz_cache: Dict[str, tuple] = {}
        logging.info("Fetching Finviz news sentiment for %d symbols", len(unique_symbols))
        for symbol in unique_symbols:
            try:
                articles = fetch_finviz_news(symbol)
                if articles:
                    score_finviz_headlines(articles)
                    upsert_finviz_news_to_mongo(symbol, articles, database=self.database)
            except Exception:  # pylint: disable=broad-except
                logging.warning("Finviz news fetch failed for %s (non-fatal)", symbol)

        for candidate in candidates:
            symbol = candidate["symbol"]
            if symbol not in finviz_cache:
                finviz_cache[symbol] = get_finviz_sentiment_score_with_count(symbol, target_date, database=self.database)
                score, count = finviz_cache[symbol]
                if score != 0.0:
                    sentiment_snapshots.append({
                        "symbol": symbol,
                        "date": target_date_str,
                        "score": score,
                        "article_count": count,
                        "source": "finviz",
                    })
            candidate["sentiment_finviz"] = finviz_cache[symbol][0]

    def _persist_snapshots(self, sentiment_snapshots: List[Dict[str, Any]], target_date_str: str) -> None:
        try:
            if sentiment_snapshots:
                saved = save_sentiment_snapshots(sentiment_snapshots, database=self.database)
                logging.info("Saved %d sentiment snapshots for %s", saved, target_date_str)
        except Exception:  # pylint: disable=broad-except
            logging.warning("Failed to save sentiment snapshots (non-fatal)")

    def _attach_composite_sentiment(self, candidates: List[Dict[str, Any]]) -> None:
        try:
            normalizer = SentimentNormalizer(database=self.database)
            normalizer.load_source_stats()
            for candidate in candidates:
                candidate["sentiment_composite"] = normalizer.composite(candidate)
        except Exception:  # pylint: disable=broad-except
            logging.warning("Composite sentiment computation failed (non-fatal)")
            for candidate in candidates:
                candidate.setdefault("sentiment_composite", 0.0)
