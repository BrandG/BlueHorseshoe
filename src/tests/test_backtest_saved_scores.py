"""
Tests for score-once, backtest-separately refactor.

Covers:
- _load_saved_predictions() transforms MongoDB score docs into prediction format
- _load_saved_predictions() returns None when no scores exist
- run_backtest() uses saved scores when available
- run_backtest() falls back to fresh calculation when no saved scores
- run_backtest() skips saved scores when use_saved_scores=False (--rescore)
"""

import pytest
from unittest.mock import patch, MagicMock, PropertyMock

from bluehorseshoe.analysis.backtest import (
    Backtester, BacktestConfig, BacktestOptions,
)


@pytest.fixture
def mock_db():
    """Create a mock database with a mock collection for ScoreManager."""
    db = MagicMock()
    collection = MagicMock()
    db.__getitem__ = MagicMock(return_value=collection)
    return db


@pytest.fixture
def backtester(mock_db):
    """Create a Backtester with mocked database."""
    return Backtester(config=BacktestConfig(), database=mock_db)


class TestLoadSavedPredictions:
    """Tests for _load_saved_predictions() method."""

    def test_transforms_baseline_format(self, backtester):
        """Mock ScoreManager.get_scores() returning score docs -> verify proper prediction dicts."""
        scores = [
            {
                'symbol': 'AAPL',
                'score': 8.5,
                'metadata': {
                    'entry_price': 150.0,
                    'stop_loss': 145.0,
                    'take_profit': 160.0,
                    'ml_win_prob': 0.72,
                    'stop_multiplier': 1.5,
                    'target_multiplier': 2.5,
                },
            },
            {
                'symbol': 'MSFT',
                'score': 7.2,
                'metadata': {
                    'entry_price': 300.0,
                    'stop_loss': 290.0,
                    'take_profit': 315.0,
                    'ml_win_prob': 0.65,
                },
            },
        ]
        backtester.score_manager.get_scores = MagicMock(return_value=scores)
        options = BacktestOptions(strategy="baseline")

        result = backtester._load_saved_predictions("2026-03-03", options)

        assert result is not None
        assert len(result) == 2

        # Check first prediction
        pred = result[0]
        assert pred['symbol'] == 'AAPL'
        assert pred['baseline_score'] == 8.5
        assert pred['baseline_setup']['entry_price'] == 150.0
        assert pred['baseline_setup']['stop_loss'] == 145.0
        assert pred['baseline_setup']['take_profit'] == 160.0
        assert pred['baseline_ml_prob'] == 0.72
        assert pred['stop_multiplier'] == 1.5
        assert pred['target_multiplier'] == 2.5

        # Check second prediction uses defaults for missing multipliers
        pred2 = result[1]
        assert pred2['symbol'] == 'MSFT'
        assert pred2['stop_multiplier'] == 2.0  # default
        assert pred2['target_multiplier'] == 3.0  # default

        # Verify get_scores called with correct strategy
        backtester.score_manager.get_scores.assert_called_once_with("2026-03-03", strategy="baseline")

    def test_transforms_mean_reversion_format(self, backtester):
        """Verify MR scores use mr_score/mr_setup/mr_ml_prob keys."""
        scores = [
            {
                'symbol': 'TSLA',
                'score': 6.0,
                'metadata': {
                    'entry_price': 200.0,
                    'stop_loss': 190.0,
                    'take_profit': 215.0,
                    'ml_win_prob': 0.58,
                },
            },
        ]
        backtester.score_manager.get_scores = MagicMock(return_value=scores)
        options = BacktestOptions(strategy="mean_reversion")

        result = backtester._load_saved_predictions("2026-03-03", options)

        assert result is not None
        assert len(result) == 1
        pred = result[0]
        assert 'mr_score' in pred
        assert 'mr_setup' in pred
        assert 'mr_ml_prob' in pred
        assert pred['mr_score'] == 6.0
        assert pred['mr_setup']['entry_price'] == 200.0

        backtester.score_manager.get_scores.assert_called_once_with("2026-03-03", strategy="mean_reversion")

    def test_returns_none_when_empty(self, backtester):
        """No scores for date -> returns None."""
        backtester.score_manager.get_scores = MagicMock(return_value=[])
        options = BacktestOptions(strategy="baseline")

        result = backtester._load_saved_predictions("2026-01-01", options)

        assert result is None

    def test_skips_entries_without_entry_price(self, backtester):
        """Scores missing entry_price in metadata are skipped."""
        scores = [
            {
                'symbol': 'GOOD',
                'score': 5.0,
                'metadata': {'entry_price': 100.0, 'stop_loss': 95.0, 'take_profit': 110.0},
            },
            {
                'symbol': 'BAD',
                'score': 4.0,
                'metadata': {},  # no entry_price
            },
        ]
        backtester.score_manager.get_scores = MagicMock(return_value=scores)
        options = BacktestOptions(strategy="baseline")

        result = backtester._load_saved_predictions("2026-03-03", options)

        assert len(result) == 1
        assert result[0]['symbol'] == 'GOOD'


class TestRunBacktestSavedScores:
    """Tests for run_backtest() integration with saved scores."""

    def test_uses_saved_scores(self, backtester):
        """When saved scores exist, _generate_predictions() should NOT be called."""
        saved_predictions = [
            {
                'symbol': 'AAPL',
                'baseline_score': 8.0,
                'baseline_setup': {'entry_price': 150.0, 'stop_loss': 145.0, 'take_profit': 160.0},
                'baseline_ml_prob': 0.7,
            },
        ]

        with patch.object(backtester, '_load_saved_predictions', return_value=saved_predictions) as mock_load, \
             patch.object(backtester, '_generate_predictions') as mock_gen, \
             patch.object(backtester, '_filter_and_sort_predictions', return_value=saved_predictions), \
             patch.object(backtester, '_evaluate_candidates', return_value=[]), \
             patch.object(backtester, '_print_summary'), \
             patch.object(backtester, '_log_results_to_csv'), \
             patch.object(backtester, '_print_backtest_header'):

            options = BacktestOptions(strategy="baseline", use_saved_scores=True)
            backtester.run_backtest("2026-03-03", options=options)

            mock_load.assert_called_once_with("2026-03-03", options)
            mock_gen.assert_not_called()

    def test_falls_back_to_fresh(self, backtester):
        """When _load_saved_predictions() returns None, _generate_predictions() IS called."""
        with patch.object(backtester, '_load_saved_predictions', return_value=None) as mock_load, \
             patch.object(backtester, '_generate_predictions', return_value=[]) as mock_gen, \
             patch.object(backtester, '_load_symbols', return_value=['AAPL', 'MSFT']), \
             patch.object(backtester, '_filter_and_sort_predictions', return_value=[]), \
             patch.object(backtester, '_print_summary'), \
             patch.object(backtester, '_log_results_to_csv'), \
             patch.object(backtester, '_print_backtest_header'):

            options = BacktestOptions(strategy="baseline", use_saved_scores=True)
            backtester.run_backtest("2026-03-03", options=options)

            mock_load.assert_called_once()
            mock_gen.assert_called_once()

    def test_rescore_flag_skips_saved(self, backtester):
        """use_saved_scores=False -> _load_saved_predictions() is NOT called."""
        with patch.object(backtester, '_load_saved_predictions') as mock_load, \
             patch.object(backtester, '_generate_predictions', return_value=[]) as mock_gen, \
             patch.object(backtester, '_load_symbols', return_value=['AAPL']), \
             patch.object(backtester, '_filter_and_sort_predictions', return_value=[]), \
             patch.object(backtester, '_print_summary'), \
             patch.object(backtester, '_log_results_to_csv'), \
             patch.object(backtester, '_print_backtest_header'):

            options = BacktestOptions(strategy="baseline", use_saved_scores=False)
            backtester.run_backtest("2026-03-03", options=options)

            mock_load.assert_not_called()
            mock_gen.assert_called_once()
