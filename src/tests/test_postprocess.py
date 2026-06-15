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
            "dollar_vol_20": 5_000_000_000.0,  # deeply liquid — clears the floor
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
        },
        {
            # DGICB-like: a real Connors setup but ~$9k/day — must be filtered off
            # the report surface by the MIN_DOLLAR_VOLUME floor.
            "symbol": "DGICB",
            "exchange": "NASDAQ",
            "dollar_vol_20": 9_000.0,
            "connors_flag": True,
            "connors_rsi2": 4.0,
            "connors_sma200": 18.0,
            "baseline_score": 25.0,
            "baseline_setup": {"entry_price": 18.0, "stop_loss": 17.0, "take_profit": 20.0},
            "baseline_components": {"trend": 2.0},
            "baseline_ml_prob": 0.5,
            "sentiment": 0.0,
        },
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
    # The illiquid name is gone from every panel, including Connors.
    assert "DGICB" not in {candidate["symbol"] for candidate in candidates}


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


def _stub_enricher_io(monkeypatch, persisted):
    """Stub all network/Mongo IO; record save_sentiment_snapshots calls in *persisted*."""
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
        lambda symbol, target_date, database=None: (0.42, 3),
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
        lambda symbol, target_date, database=None: (1.0, 10),
    )
    monkeypatch.setattr(
        "bluehorseshoe.analysis.postprocess.get_finviz_sentiment_score_with_count",
        lambda symbol, target_date, database=None: (0.0, 0),
    )
    monkeypatch.setattr(
        "bluehorseshoe.analysis.postprocess.save_sentiment_snapshots",
        lambda snapshots, database=None: persisted.append(snapshots) or len(snapshots),
    )
    monkeypatch.setattr(
        "bluehorseshoe.analysis.postprocess.get_settings",
        lambda: MagicMock(tiingo_api_key=""),
    )


def test_sentiment_enricher_archives_snapshots_only_on_live_runs(monkeypatch):
    """Historical/backtest/eval runs must NOT write sentiment_snapshots: the live
    feeds describe *now*, and stamping them onto historical dates poisons the
    point-in-time archive (the pre-2026-04 contamination). Default is fail-closed."""
    persisted = []
    _stub_enricher_io(monkeypatch, persisted)

    candidates = [{"symbol": "AAPL", "strategy": "DeepOS", "score": 10.0}]
    enricher = SentimentEnricher(database=MagicMock())

    # Historical run (explicit) - nothing persisted
    enricher.enrich(
        [dict(c) for c in candidates],
        target_date="2022-02-03", market_health={"details": {}}, is_live=False,
    )
    assert persisted == []

    # Default omits is_live - fail-closed, nothing persisted
    enricher.enrich(
        [dict(c) for c in candidates],
        target_date="2022-02-03", market_health={"details": {}},
    )
    assert persisted == []

    # Live run - snapshots persisted (AV + StockTwits nonzero scores above)
    enricher.enrich(
        [dict(c) for c in candidates],
        target_date="2026-06-10", market_health={"details": {}}, is_live=True,
    )
    assert len(persisted) == 1
    sources = {snap["source"] for snap in persisted[0]}
    assert sources == {"alphavantage", "stocktwits"}


def test_is_live_target_date_fails_closed(monkeypatch):
    """Liveness gate: latest-date match -> live; mismatch, resolution failure, or
    missing latest -> historical (fail-closed, protects the snapshot archive)."""
    from types import SimpleNamespace

    from bluehorseshoe.analysis.strategy import SwingTrader

    fake = SimpleNamespace(database=MagicMock(), store=MagicMock())
    check = lambda td: SwingTrader._is_live_target_date(fake, td)

    monkeypatch.setattr(
        "bluehorseshoe.analysis.strategy.get_latest_market_date",
        lambda database=None, store=None: "2026-06-10",
    )
    assert check("2026-06-10") is True
    assert check("2022-02-03") is False
    assert check(None) is True  # no date constraint = predicting on latest data

    monkeypatch.setattr(
        "bluehorseshoe.analysis.strategy.get_latest_market_date",
        lambda database=None, store=None: None,
    )
    assert check("2026-06-10") is False

    def boom(database=None, store=None):
        raise RuntimeError("store unavailable")
    monkeypatch.setattr("bluehorseshoe.analysis.strategy.get_latest_market_date", boom)
    assert check("2026-06-10") is False
