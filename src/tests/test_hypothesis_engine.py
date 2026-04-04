from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from pymongo.errors import BulkWriteError

from bluehorseshoe.analysis.hypothesis_engine import HypothesisEngine
from bluehorseshoe.analysis.trade_evaluator import (
    TradeEvalConfig,
    TradeEvalState,
    check_active_trade,
    check_entry,
    evaluate_bars,
)
from bluehorseshoe.data.duckdb_store import DuckDBStore


def make_bars(rows):
    return pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])


def test_evaluate_bars_target_hit():
    bars = make_bars([
        ("2026-01-02", 100.0, 101.0, 98.0, 99.5, 1000),
        ("2026-01-03", 99.5, 103.0, 98.5, 102.0, 1000),
        ("2026-01-04", 104.0, 106.0, 103.0, 105.0, 1000),
    ])

    result = evaluate_bars(
        bars, entry_price=100.0, stop_loss=96.0, take_profit=105.0,
        config=TradeEvalConfig(hold_days=5),
    )

    assert result["outcome"] == "WIN"
    assert result["exit_reason"] == "target"
    assert result["pnl_pct"] > 0
    assert result["days_held"] >= 1


def test_evaluate_bars_stop_hit():
    bars = make_bars([
        ("2026-01-02", 100.0, 101.0, 98.0, 99.5, 1000),
        ("2026-01-03", 95.0, 96.0, 94.0, 95.5, 1000),
    ])

    result = evaluate_bars(
        bars, entry_price=100.0, stop_loss=96.0, take_profit=110.0,
        config=TradeEvalConfig(hold_days=5),
    )

    assert result["outcome"] == "LOSS"
    assert result["exit_reason"] == "stop"
    assert result["pnl_pct"] < 0


def test_evaluate_bars_timeout():
    bars = make_bars([
        ("2026-01-02", 100.0, 101.0, 98.0, 99.5, 1000),
        ("2026-01-03", 100.0, 101.0, 99.0, 100.5, 1000),
        ("2026-01-04", 100.5, 101.0, 99.0, 100.0, 1000),
        ("2026-01-05", 100.0, 101.0, 99.0, 100.2, 1000),
        ("2026-01-06", 100.2, 101.0, 99.0, 100.1, 1000),
        ("2026-01-07", 100.1, 101.0, 99.0, 100.3, 1000),
    ])

    result = evaluate_bars(
        bars, entry_price=100.0, stop_loss=96.0, take_profit=110.0,
        config=TradeEvalConfig(hold_days=5),
    )

    assert result["outcome"] == "TIMEOUT"
    assert result["exit_reason"] == "time_exit"


def test_evaluate_bars_not_entered():
    bars = make_bars([
        ("2026-01-02", 101.0, 103.0, 100.0, 102.0, 1000),
        ("2026-01-03", 101.5, 103.0, 100.2, 102.5, 1000),
        ("2026-01-04", 102.0, 104.0, 100.5, 103.0, 1000),
        ("2026-01-05", 101.8, 104.0, 100.1, 103.2, 1000),
        ("2026-01-06", 102.0, 104.0, 100.3, 103.4, 1000),
        ("2026-01-07", 102.1, 104.0, 100.4, 103.5, 1000),
    ])

    result = evaluate_bars(
        bars, entry_price=100.0, stop_loss=96.0, take_profit=110.0,
        config=TradeEvalConfig(hold_days=5),
    )

    assert result["outcome"] == "NOT_ENTERED"
    assert result["actual_entry"] is None
    assert result["pnl_pct"] == 0.0


def test_evaluate_bars_gap_down_slippage():
    bars = make_bars([
        ("2026-01-02", 97.0, 101.0, 96.5, 99.0, 1000),
        ("2026-01-03", 99.0, 111.0, 98.0, 110.0, 1000),
    ])

    result = evaluate_bars(
        bars, entry_price=100.0, stop_loss=95.0, take_profit=110.0,
        config=TradeEvalConfig(hold_days=5),
    )

    assert result["actual_entry"] == 97.0


def test_evaluate_bars_entry_buffer():
    bars = make_bars([
        ("2026-01-02", 100.0, 101.0, 99.95, 100.2, 1000),
        ("2026-01-03", 100.2, 101.0, 99.95, 100.3, 1000),
    ])

    result = evaluate_bars(
        bars, entry_price=100.0, stop_loss=96.0, take_profit=105.0,
        config=TradeEvalConfig(hold_days=1),
    )

    assert result["outcome"] == "NOT_ENTERED"


def test_evaluate_bars_mae_mfe():
    bars = make_bars([
        ("2026-01-02", 100.0, 101.0, 98.0, 99.5, 1000),
        ("2026-01-03", 99.5, 100.5, 97.0, 98.5, 1000),
        ("2026-01-04", 98.5, 104.0, 98.0, 103.5, 1000),
        ("2026-01-05", 104.0, 106.0, 103.0, 105.0, 1000),
    ])

    result = evaluate_bars(
        bars, entry_price=100.0, stop_loss=96.0, take_profit=105.0,
        config=TradeEvalConfig(hold_days=5),
    )

    expected_mae = (97.0 - result["actual_entry"]) / result["actual_entry"]
    assert result["mae_pct"] < 0
    assert result["mfe_pct"] > 0
    assert result["mae_pct"] == pytest.approx(expected_mae)


def test_evaluate_bars_same_bar_entry_and_stop():
    bars = make_bars([
        ("2026-01-02", 100.0, 101.0, 95.0, 96.0, 1000),
    ])

    result = evaluate_bars(
        bars, entry_price=100.0, stop_loss=96.0, take_profit=110.0,
        config=TradeEvalConfig(hold_days=5),
    )

    assert result["outcome"] == "LOSS"
    assert result["days_held"] == 0


def test_evaluate_bars_same_bar_entry_and_target():
    bars = make_bars([
        ("2026-01-02", 100.0, 106.0, 99.0, 105.0, 1000),
    ])

    result = evaluate_bars(
        bars, entry_price=100.0, stop_loss=95.0, take_profit=105.0,
        config=TradeEvalConfig(hold_days=5),
    )

    assert result["outcome"] == "WIN"
    assert result["days_held"] == 0


def test_evaluate_bars_empty_dataframe():
    bars = make_bars([])

    result = evaluate_bars(
        bars, entry_price=100.0, stop_loss=95.0, take_profit=105.0,
        config=TradeEvalConfig(hold_days=5),
    )

    assert result["outcome"] == "NOT_ENTERED"


def test_check_entry_sets_active_state():
    state = TradeEvalState(
        entry_price=100.0,
        adjusted_entry=99.9,
        take_profit=105.0,
        stop_loss=96.0,
    )
    row = {
        "date": "2026-01-02",
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.0,
    }

    check_entry(row, 0, state, hold_days=5)

    assert state.status == "active"
    assert state.actual_entry == pytest.approx(99.9)
    assert state.entry_date == "2026-01-02"


def test_check_active_trade_updates_mae_mfe():
    state = TradeEvalState(
        entry_price=100.0,
        adjusted_entry=99.9,
        take_profit=110.0,
        stop_loss=96.0,
        status="active",
        actual_entry=99.9,
        entry_date="2026-01-02",
        entry_idx=0,
    )
    row = {
        "date": "2026-01-03",
        "open": 100.0,
        "high": 104.0,
        "low": 97.0,
        "close": 101.0,
    }

    check_active_trade(row, 1, state, hold_days=5)

    assert state.status == "active"
    assert state.mae_pct < 0
    assert state.mfe_pct > 0


@pytest.fixture
def mock_db():
    db = MagicMock()
    collections = {
        "journal_batches": MagicMock(),
        "journal_signals": MagicMock(),
        "journal_hypothetical_trades": MagicMock(),
    }
    db.__getitem__.side_effect = lambda key: collections[key]
    return db


@pytest.fixture
def mock_store():
    return MagicMock(spec=DuckDBStore)


@pytest.fixture
def engine(mock_db, mock_store):
    with patch.object(HypothesisEngine, "_ensure_indexes"):
        return HypothesisEngine(database=mock_db, store=mock_store)


def test_get_hold_days_bearish(engine):
    assert engine._get_hold_days({"market_regime": {"status": "Bearish"}}) == 7


def test_get_hold_days_bullish(engine):
    assert engine._get_hold_days({"market_regime": {"status": "Bullish"}}) == 5


def test_get_hold_days_unknown_defaults_neutral(engine):
    assert engine._get_hold_days({"market_regime": {"status": "Unknown"}}) == 5


def test_find_mature_batches_skips_immature(engine):
    batch_cursor = MagicMock()
    batch_cursor.sort.return_value = [{"batch_date": "2026-03-01", "market_regime": {"status": "Bearish"}}]
    engine._batches.find.return_value = batch_cursor

    with patch.object(engine, "_is_mature", return_value=False):
        result = engine.find_mature_batches(as_of_date="2026-04-01")

    assert result == []


def test_find_mature_batches_skips_fully_evaluated(engine):
    batch_cursor = MagicMock()
    batch_cursor.sort.return_value = [{"batch_date": "2026-03-01", "market_regime": {"status": "Bearish"}}]
    engine._batches.find.return_value = batch_cursor
    engine._signals.count_documents.return_value = 2
    engine._results.count_documents.return_value = 2

    with patch.object(engine, "_is_mature", return_value=True):
        result = engine.find_mature_batches(as_of_date="2026-04-01")

    assert result == []


def test_evaluate_batch_idempotent(engine):
    batch_doc = {"batch_date": "2026-03-01", "market_regime": {"status": "Bearish"}}
    signals = [{
        "batch_date": "2026-03-01",
        "symbol": "AAPL",
        "strategy": "baseline",
        "composite_score": 10.0,
        "signal_strength": "HIGH",
        "rank": 1,
        "ml_win_probability": 0.7,
        "entry_price": 100.0,
        "stop_loss": 95.0,
        "take_profit_t2": 105.0,
    }]
    engine._signals.find.return_value = signals
    engine._store.load_symbols_bulk.return_value = {
        "AAPL": make_bars([
            ("2026-03-02", 100.0, 101.0, 98.0, 99.5, 1000),
            ("2026-03-03", 101.0, 106.0, 100.0, 105.0, 1000),
        ]),
        "SPY": make_bars([
            ("2026-03-02", 500.0, 505.0, 499.0, 504.0, 1000),
            ("2026-03-03", 504.0, 506.0, 503.0, 505.0, 1000),
        ]),
    }
    engine._results.insert_many.side_effect = BulkWriteError({"writeErrors": [], "nInserted": 0})

    summary = engine.evaluate_batch(batch_doc)

    assert summary["evaluated"] == 0
    assert summary["skipped_duplicates"] == 1
    assert summary["errors"] == 0


def test_compute_spy_return(engine):
    spy_df = make_bars([
        ("2026-03-02", 500.0, 505.0, 499.0, 504.0, 1000),
        ("2026-03-03", 504.0, 508.0, 503.0, 507.0, 1000),
        ("2026-03-04", 507.0, 510.0, 506.0, 509.0, 1000),
    ])

    result = engine._compute_spy_return(spy_df, "2026-03-02", "2026-03-04")

    assert result == pytest.approx((509.0 - 500.0) / 500.0)


def test_run_no_mature_batches(engine):
    with patch.object(engine, "find_mature_batches", return_value=[]):
        assert engine.run() == []
