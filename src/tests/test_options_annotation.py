"""Tests for tracking-only options-fear annotation."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from bluehorseshoe.analysis.options_annotation import (
    ANNOTATION_CAP,
    DD10_DEEP_CUT,
    SK_FEAR_CUT,
    annotate_deepos_results,
    classify_arm,
    compute_dd10,
    compute_options_features,
)


def _contract(exp, strike, typ, iv, delta):
    return {
        "expiration": exp,
        "strike": str(strike),
        "type": typ,
        "implied_volatility": str(iv),
        "delta": str(delta),
    }


def _fixture_chain():
    return [
        _contract("2026-06-20", 95, "put", 0.99, -0.99),     # excluded by delta slim
        _contract("2026-07-11", 100, "put", 0.30, -0.24),    # selected put25
        _contract("2026-07-11", 102, "put", 0.60, -0.44),    # farther from target
        _contract("2026-07-11", 100, "call", 0.19, 0.20),    # selected call25
        _contract("2026-07-11", 105, "call", 0.40, 0.44),    # farther from target
        _contract("2026-07-11", 100, "call", 0.21, 0.50),    # ATM IV, not 25d band
        _contract("2026-08-15", 100, "put", 0.70, -0.25),    # valid but non-target dte
        _contract("2026-10-01", 100, "put", 0.80, -0.25),    # excluded by dte
    ]


def test_compute_options_features_research_math():
    feats = compute_options_features(_fixture_chain(), "2026-06-11", close=101.0)

    assert feats["dte_used"] == 30
    assert feats["n_contracts"] == 6
    assert feats["skew"] == pytest.approx(0.11)
    assert feats["atm_iv"] == pytest.approx((0.30 + 0.19 + 0.21) / 3)


def test_junk_quote_chain_becomes_deep_nochain():
    chain = [
        _contract("2026-07-11", 100, "put", 0.001, -0.25),
        _contract("2026-07-11", 100, "call", 5.5, 0.25),
    ]
    feats = compute_options_features(chain, "2026-06-11", close=100.0)

    assert feats["skew"] is None
    assert feats["atm_iv"] is None
    assert classify_arm(DD10_DEEP_CUT + 0.01, feats) == "deep_nochain"


def test_classify_arm_matrix_and_boundaries():
    assert classify_arm(float("nan"), {"skew": SK_FEAR_CUT + 0.01}) == "shallow"
    assert classify_arm(DD10_DEEP_CUT, {"skew": SK_FEAR_CUT + 0.01}) == "shallow"
    assert classify_arm(DD10_DEEP_CUT + 0.01, None) == "deep_nochain"
    assert classify_arm(DD10_DEEP_CUT + 0.01, {"skew": SK_FEAR_CUT + 0.01}) == "deep_fear"
    assert classify_arm(DD10_DEEP_CUT + 0.01, {"skew": SK_FEAR_CUT}) == "deep_calm"


def test_compute_dd10():
    closes = [110, 108, 107, 105, 100]
    assert compute_dd10(closes, 2.0) == pytest.approx(5.0)
    assert pd.isna(compute_dd10(closes, 0.0))


def test_annotate_fetch_failure_leaves_row_unannotated():
    def fetch(symbol):
        if symbol == "AAPL":
            raise RuntimeError("rate limited")
        return []

    rows = [
        {
            "symbol": "AAPL",
            "date": "2026-06-11",
            "deep_os_score": 5.0,
            "deep_os_setup": {"actual_close": 100.0},
            "options_history": {"closes": [110.0, 100.0], "atr": 1.0},
        },
        {
            "symbol": "NVDA",
            "date": "2026-06-11",
            "deep_os_score": 2.0,
            "deep_os_setup": {"actual_close": 100.0},
            "options_history": {"closes": [110.0, 100.0], "atr": 1.0},
        },
    ]

    n = annotate_deepos_results(rows, target_date="2026-06-11", fetch=fetch)

    assert n == 1
    assert "options_arm" not in rows[0]
    assert rows[1]["options_arm"] == "deep_nochain"
    assert rows[1]["options_skew"] is None


def test_annotate_caps_symbols(caplog):
    calls = []

    def fetch(symbol):
        calls.append(symbol)
        return []

    rows = [
        {
            "symbol": f"SYM{i:03d}",
            "date": "2026-06-11",
            "deep_os_score": 1.0,
            "deep_os_setup": {"actual_close": 100.0},
            "options_history": {"closes": [110.0, 100.0], "atr": 1.0},
        }
        for i in range(ANNOTATION_CAP + 2)
    ]

    n = annotate_deepos_results(rows, target_date="2026-06-11", fetch=fetch)

    assert len(calls) == ANNOTATION_CAP
    assert n == ANNOTATION_CAP
    assert "dropping 2" in caplog.text
    assert sum(1 for row in rows if "options_arm" in row) == ANNOTATION_CAP


def test_non_live_target_date_skips_options_annotation():
    from bluehorseshoe.analysis.strategy import SwingTrader

    db = MagicMock()
    db.__getitem__.return_value.find.return_value = [{"symbol": "AAPL"}]
    trader = SwingTrader.__new__(SwingTrader)
    trader.database = db
    trader.store = None
    trader.strategies = []
    trader.config = SimpleNamespace(
        holiday_mode=True,
        paper_trading_enabled=False,
        paper_total_investment=0,
        paper_max_positions=0,
        paper_slots_deep_oversold=0,
        paper_conviction_sizing=False,
        paper_max_position_mult=1.0,
    )
    trader.score_manager = MagicMock()
    trader.signal_journal = None
    trader.report_writer = None
    trader._write_report = MagicMock()
    trader._load_benchmark_data = MagicMock(return_value=None)
    trader._execute_prediction_batch = MagicMock(return_value=[{
        "symbol": "AAPL",
        "date": "2026-06-11",
        "deep_os_score": 1.0,
        "deep_os_setup": {"actual_close": 100.0},
    }])
    trader._enrich_with_intraday = MagicMock(return_value=[])
    trader._annotate_planned_sizing = MagicMock()
    trader._is_live_target_date = MagicMock(return_value=False)

    with patch("bluehorseshoe.analysis.strategy.MarketRegime.get_market_health",
               return_value={"status": "Neutral", "multiplier": 1.0}), \
         patch("bluehorseshoe.analysis.strategy.get_symbols",
               return_value=[{"symbol": "AAPL", "exchange": "NASDAQ"}]), \
         patch("bluehorseshoe.analysis.strategy.CandidateAssembler") as assembler_cls, \
         patch("bluehorseshoe.analysis.strategy.SentimentEnricher") as enricher_cls, \
         patch("bluehorseshoe.analysis.strategy.annotate_options_deepos_results") as annot:
        assembler_cls.return_value.build_top_candidates.return_value = []
        enricher_cls.return_value.enrich.return_value = []
        trader.swing_predict(target_date="2026-06-01", symbols=["AAPL"])

    annot.assert_not_called()


def test_journal_docs_carry_options_annotation():
    from bluehorseshoe.core.journal import SignalJournal

    rows = [{
        "symbol": "AAPL",
        "deep_os_score": 5.0,
        "deep_os_setup": {"entry_price": 100.0, "stop_loss": 97.0, "take_profit": 106.0},
        "options_skew": 0.12,
        "options_atm_iv": 0.30,
        "options_dte": 30,
        "options_dd10": 5.0,
        "options_arm": "deep_fear",
    }]
    docs = SignalJournal._build_signal_docs(MagicMock(), "2026-06-11", rows)
    deep = [doc for doc in docs if doc["strategy"] == "deep_oversold"]

    assert deep[0]["options_skew"] == 0.12
    assert deep[0]["options_atm_iv"] == 0.30
    assert deep[0]["options_dte"] == 30
    assert deep[0]["options_dd10"] == 5.0
    assert deep[0]["options_arm"] == "deep_fear"


def test_hypothesis_docs_carry_options_annotation():
    from bluehorseshoe.analysis.hypothesis_engine import HypothesisEngine

    db = MagicMock()
    collections = {
        "journal_batches": MagicMock(),
        "journal_signals": MagicMock(),
        "journal_hypothetical_trades": MagicMock(),
    }
    db.__getitem__.side_effect = lambda key: collections[key]
    engine = HypothesisEngine(database=db, store=MagicMock())
    batch_doc = {"batch_date": "2026-03-01", "market_regime": {"status": "Bullish"}}
    engine._signals.find.return_value = [{
        "batch_date": "2026-03-01",
        "symbol": "AAPL",
        "strategy": "deep_oversold",
        "composite_score": 10.0,
        "signal_strength": "HIGH",
        "rank": 1,
        "ml_win_probability": 0.7,
        "entry_price": 100.0,
        "stop_loss": 95.0,
        "take_profit_t2": 105.0,
        "options_skew": 0.12,
        "options_atm_iv": 0.30,
        "options_dte": 30,
        "options_dd10": 5.0,
        "options_arm": "deep_fear",
    }]
    engine._store.load_symbols_bulk.return_value = {
        "AAPL": pd.DataFrame(
            [("2026-03-02", 100.0, 106.0, 98.0, 105.0, 1000)],
            columns=["date", "open", "high", "low", "close", "volume"],
        ),
        "SPY": pd.DataFrame(
            [("2026-03-02", 500.0, 505.0, 499.0, 504.0, 1000)],
            columns=["date", "open", "high", "low", "close", "volume"],
        ),
    }
    engine._results.insert_many.return_value = MagicMock(inserted_ids=[1])

    engine.evaluate_batch(batch_doc, as_of_date="2026-03-30")

    docs = engine._results.insert_many.call_args.args[0]
    assert docs[0]["options_skew"] == 0.12
    assert docs[0]["options_atm_iv"] == 0.30
    assert docs[0]["options_dte"] == 30
    assert docs[0]["options_dd10"] == 5.0
    assert docs[0]["options_arm"] == "deep_fear"
