from unittest.mock import MagicMock

from bluehorseshoe.analysis.postprocess import CandidateAssembler, SentimentEnricher
from bluehorseshoe.analysis.strategy_registry import get_all_strategies


def test_candidate_assembler_skips_untraded_sleeves_keeps_live_and_connors():
    """Untraded Baseline/MeanRev never become candidate rows (their rankings
    anti-select); live DeepOS sleeves do, and Connors still rides the
    Baseline/MeanRev setup metadata."""
    assembler = CandidateAssembler(get_all_strategies())
    valid_results = [
        {
            "symbol": "AAPL",
            "exchange": "NASDAQ",
            "connors_flag": True,
            "connors_rsi2": 5.3,
            "connors_sma200": 150.0,
            "mr_score": 45.0,
            "mr_setup": {"entry_price": 155.0, "stop_loss": 148.0, "take_profit": 165.0},
            "mr_components": {"rsi": -2.0},
            "mr_ml_prob": 0.65,
            "baseline_score": 30.0,
            "baseline_setup": {"entry_price": 155.0, "stop_loss": 148.0, "take_profit": 165.0},
            "baseline_components": {"trend": 3.0},
            "baseline_ml_prob": 0.55,
            "deep_os_score": 12.0,
            "deep_os_setup": {"entry_price": 155.0, "stop_loss": 148.0, "take_profit": 165.0},
            "deep_os_components": {"rsi_depth": 4.0},
            "deep_os_ml_prob": 0.5,
            "sentiment": 0.1,
        }
    ]

    candidates = assembler.build_top_candidates(valid_results)

    strategies = {candidate["strategy"] for candidate in candidates}
    assert "Baseline" not in strategies
    assert "MeanRev" not in strategies
    assert "DeepOS" in strategies
    assert "Connors" in strategies
    connors = next(candidate for candidate in candidates if candidate["strategy"] == "Connors")
    assert connors["connors_rsi2"] == 5.3
    assert connors["close"] == 155.0


def test_sentiment_enricher_falls_back_to_zero_composite(monkeypatch):
    candidates = [{"symbol": "AAPL", "strategy": "Baseline", "score": 10.0}]

    monkeypatch.setattr(
        "bluehorseshoe.analysis.postprocess.fetch_news_sentiment_from_net",
        lambda symbol: {"feed": []},
    )
    monkeypatch.setattr(
        "bluehorseshoe.analysis.postprocess.upsert_news_sentiment_to_mongo",
        lambda symbol, news_data, database=None: None,
    )
    monkeypatch.setattr(
        "bluehorseshoe.analysis.postprocess.get_sentiment_score_with_count",
        lambda symbol, target_date, database=None: (0.0, 0),
    )
    monkeypatch.setattr(
        "bluehorseshoe.analysis.postprocess.fetch_stocktwits_messages",
        lambda symbol: [],
    )
    monkeypatch.setattr(
        "bluehorseshoe.analysis.postprocess.fetch_finviz_news",
        lambda symbol: [],
    )
    monkeypatch.setattr(
        "bluehorseshoe.analysis.postprocess.get_stocktwits_sentiment_score_with_count",
        lambda symbol, target_date, database=None: (0.0, 0),
    )
    monkeypatch.setattr(
        "bluehorseshoe.analysis.postprocess.get_finviz_sentiment_score_with_count",
        lambda symbol, target_date, database=None: (0.0, 0),
    )
    monkeypatch.setattr(
        "bluehorseshoe.analysis.postprocess.save_sentiment_snapshots",
        lambda snapshots, database=None: len(snapshots),
    )

    class BrokenNormalizer:
        def __init__(self, database=None):
            pass

        def load_source_stats(self):
            raise RuntimeError("boom")

    monkeypatch.setattr("bluehorseshoe.analysis.postprocess.SentimentNormalizer", BrokenNormalizer)
    monkeypatch.setattr("bluehorseshoe.analysis.postprocess.get_settings", lambda: MagicMock(tiingo_api_key=""))

    enricher = SentimentEnricher(database=MagicMock())
    result = enricher.enrich(candidates, target_date="2026-03-26", market_health={"details": {}})

    assert result[0]["sentiment"] == 0.0
    assert result[0]["sentiment_stocktwits"] == 0.0
    assert result[0]["sentiment_finviz"] == 0.0
    assert result[0]["sentiment_composite"] == 0.0
