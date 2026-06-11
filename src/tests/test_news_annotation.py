"""Tests for the tracking-only 48h news annotation (analysis/news_annotation.py)."""
from unittest.mock import MagicMock

from bluehorseshoe.analysis.news_annotation import (
    SQ_LOW_CUT,
    annotate_deepos_results,
    classify_arm,
    compute_news_48h,
)


def _article(day, ticker="AAPL", rel=0.8, score=-0.4):
    return {
        "time_published": f"{day}T120000",
        "ticker_sentiment": [
            {"ticker": ticker, "relevance_score": str(rel), "ticker_sentiment_score": str(score)},
        ],
    }


def test_compute_news_48h_window_and_weighting():
    feed = [
        _article("20260608", score=-0.5),   # before window (target-3d) - excluded
        _article("20260609", rel=0.5, score=-0.6),  # in window
        _article("20260611", rel=1.0, score=-0.3),  # signal day - included
        _article("20260612", score=0.9),    # after signal day - excluded
    ]
    mean, count = compute_news_48h(feed, "AAPL", "2026-06-11")
    assert count == 2
    expected = (0.5 * -0.6 + 1.0 * -0.3) / 1.5
    assert abs(mean - expected) < 1e-9


def test_compute_news_48h_filters_relevance_and_ticker():
    feed = [
        _article("20260610", rel=0.1, score=-0.9),       # passing mention - dropped
        _article("20260610", ticker="MSFT", score=-0.9), # other ticker - dropped
    ]
    assert compute_news_48h(feed, "AAPL", "2026-06-11") == (None, 0)
    assert compute_news_48h([], "AAPL", "2026-06-11") == (None, 0)
    assert compute_news_48h(None, "AAPL", "not-a-date") == (None, 0)


def test_classify_arm_uses_frozen_research_cut():
    assert classify_arm(None, 0) == "nocov"
    assert classify_arm(SQ_LOW_CUT, 3) == "sq_low"      # cut is inclusive
    assert classify_arm(SQ_LOW_CUT + 0.01, 3) == "rest"
    assert classify_arm(-0.5, 1) == "sq_low"


def test_annotate_targets_deepos_family_only(monkeypatch):
    monkeypatch.setattr(
        "bluehorseshoe.analysis.news_annotation.upsert_news_sentiment_to_mongo",
        lambda symbol, news_data, database=None: None,
    )
    rows = [
        {"symbol": "AAPL", "date": "2026-06-11", "deep_os_score": 5.0},
        {"symbol": "NVDA", "date": "2026-06-11", "deep_os_ha_score": 3.0},
        {"symbol": "MSFT", "date": "2026-06-11", "baseline_score": 9.0},  # not DeepOS family
    ]
    feed = {"feed": [_article("20260611", ticker="AAPL", score=-0.4),
                     _article("20260611", ticker="NVDA", score=0.5)]}
    n = annotate_deepos_results(
        rows, target_date="2026-06-11", database=MagicMock(), fetch=lambda s: feed,
    )
    assert n == 2
    assert rows[0]["news_48h_arm"] == "sq_low"
    assert rows[1]["news_48h_arm"] == "rest"
    assert "news_48h_arm" not in rows[2]


def test_annotate_fetch_failure_leaves_row_unannotated(monkeypatch):
    monkeypatch.setattr(
        "bluehorseshoe.analysis.news_annotation.upsert_news_sentiment_to_mongo",
        lambda symbol, news_data, database=None: None,
    )

    def fetch(symbol):
        if symbol == "AAPL":
            raise RuntimeError("rate limited")
        return {"feed": []}

    rows = [
        {"symbol": "AAPL", "date": "2026-06-11", "deep_os_score": 5.0},
        {"symbol": "NVDA", "date": "2026-06-11", "deep_os_score": 2.0},
    ]
    n = annotate_deepos_results(rows, target_date="2026-06-11", database=MagicMock(), fetch=fetch)
    assert n == 1
    assert "news_48h_arm" not in rows[0]          # failed fetch: absent, not fabricated
    assert rows[1]["news_48h_arm"] == "nocov"     # empty feed: annotated as uncovered
    assert rows[1]["news_48h_mean"] is None
    assert rows[1]["news_48h_count"] == 0


def test_annotate_caps_symbols(monkeypatch):
    monkeypatch.setattr(
        "bluehorseshoe.analysis.news_annotation.upsert_news_sentiment_to_mongo",
        lambda symbol, news_data, database=None: None,
    )
    calls = []

    def fetch(symbol):
        calls.append(symbol)
        return {"feed": []}

    rows = [{"symbol": f"SYM{i:03d}", "date": "2026-06-11", "deep_os_score": 1.0} for i in range(10)]
    n = annotate_deepos_results(
        rows, target_date="2026-06-11", database=MagicMock(), fetch=fetch, max_symbols=4,
    )
    assert len(calls) == 4
    assert n == 4
    assert sum(1 for r in rows if "news_48h_arm" in r) == 4


def test_journal_docs_carry_annotation():
    from bluehorseshoe.core.journal import SignalJournal

    rows = [{
        "symbol": "AAPL",
        "deep_os_score": 5.0,
        "deep_os_setup": {"entry_price": 100.0, "stop_loss": 97.0, "take_profit": 106.0},
        "news_48h_mean": -0.42,
        "news_48h_count": 3,
        "news_48h_arm": "sq_low",
    }]
    docs = SignalJournal._build_signal_docs(MagicMock(), "2026-06-11", rows)
    deep = [d for d in docs if d["strategy"] == "deep_oversold"]
    assert deep, "expected a deep_oversold journal doc"
    assert deep[0]["news_48h_arm"] == "sq_low"
    assert deep[0]["news_48h_mean"] == -0.42
    assert deep[0]["news_48h_count"] == 3
