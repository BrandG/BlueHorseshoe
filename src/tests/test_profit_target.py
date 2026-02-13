"""
Unit tests for profit target ML model.
"""
# pylint: disable=redefined-outer-name
import pytest
import pandas as pd
from unittest.mock import MagicMock
from bluehorseshoe.analysis.grading_engine import GradingEngine, TradeResult
from bluehorseshoe.analysis.ml_profit_target import ProfitTargetTrainer, ProfitTargetInference

@pytest.fixture
def mock_database():
    """Create a mock database for testing."""
    mock_db = MagicMock()
    # Mock symbol_overviews collection
    mock_overviews_col = MagicMock()
    mock_overviews_col.find_one.return_value = {
        "Sector": "Technology",
        "Industry": "Software",
        "MarketCapitalization": "1000000000",
        "Beta": "1.2",
        "PERatio": "25"
    }
    # Mock symbol_news collection
    mock_news_col = MagicMock()
    mock_news_col.find_one.return_value = {"feed": []}
    # Mock trade_scores collection
    mock_scores_col = MagicMock()
    # Mock daily_data collection
    mock_daily_col = MagicMock()
    mock_daily_col.insert_one.return_value = MagicMock()
    mock_daily_col.find_one.return_value = None

    mock_db.__getitem__.side_effect = lambda key: {
        "symbol_overviews": mock_overviews_col,
        "symbol_news": mock_news_col,
        "trade_scores": mock_scores_col,
        "daily_data": mock_daily_col
    }.get(key, MagicMock())

    return mock_db

@pytest.fixture
def base_data():
    """Provides a base DataFrame for testing."""
    return pd.DataFrame({
        "date": pd.date_range(start="2025-12-01", periods=30),
        "open": [100.0] * 30,
        "high": [105.0] * 30,
        "low": [95.0] * 30,
        "close": [100.0 + (1.0 if i % 2 == 0 else -1.0) for i in range(30)],
        "volume": [200000] * 30,
        "avg_volume_20": [200000] * 30,
        "rsi_14": [50.0] * 30,
        "bb_lower": [90.0] * 30,
        "bb_upper": [110.0] * 30,
        "stoch_k": [50.0] * 30,
        "stoch_d": [50.0] * 30,
        "dmi_p": [20.0] * 30,
        "dmi_n": [20.0] * 30,
        "adx": [20.0] * 30,
        "macd_line": [0.0] * 30,
        "macd_signal": [0.0] * 30,
        "atr_14": [2.0] * 30
    })

def test_grading_engine_returns_mfe_atr():
    """Test that TradeResult includes max_high field."""
    result = TradeResult(
        status='success',
        exit_price=105.0,
        exit_date='2026-01-15',
        max_gain=5.0,
        max_high=105.0,
        min_low=98.0,
        days_held=5
    )

    assert hasattr(result, 'max_high')
    assert result.max_high == 105.0

def test_grading_engine_calculates_mfe_atr(base_data, mock_database):
    """Test that grading engine calculates mfe_atr from max_high."""
    # Create a mock score document
    score_doc = {
        'symbol': 'TEST',
        'date': '2026-01-01',
        'score': 50.0,
        'strategy': 'baseline',
        'metadata': {
            'entry_price': 100.0,
            'stop_loss': 98.0,
            'take_profit': 106.0,
            'components': {}
        }
    }

    # Create price data with future days
    df = base_data.copy()
    df['date'] = pd.date_range(start='2025-12-15', periods=len(df), freq='D').strftime('%Y-%m-%d')
    df['atr_14'] = 2.0  # Fixed ATR for testing

    # Add to mock database
    mock_database['daily_data'].insert_one({
        'symbol': 'TEST',
        'days': df.to_dict('records')
    })

    # Run grading
    engine = GradingEngine(hold_days=10, database=mock_database)
    result = engine._evaluate_with_df(score_doc, df)

    # Verify mfe_atr is calculated
    assert 'mfe_atr' in result
    assert isinstance(result['mfe_atr'], float)
    assert result['mfe_atr'] >= 0  # MFE should be non-negative

    # Also verify mae_atr is still there
    assert 'mae_atr' in result
    assert isinstance(result['mae_atr'], float)

def test_profit_target_trainer_initialization(mock_database):
    """Test that ProfitTargetTrainer can be initialized."""
    trainer = ProfitTargetTrainer(
        model_path="src/models/test_model.joblib",
        database=mock_database
    )
    assert trainer.model_path == "src/models/test_model.joblib"
    assert trainer.database is mock_database
    assert trainer.grading_engine is not None

def test_profit_target_trainer_handles_empty_data(mock_database):
    """Test that trainer handles empty grading results gracefully."""
    trainer = ProfitTargetTrainer(database=mock_database)

    # Should return empty DataFrame when no data available
    df = trainer.prepare_training_data(limit=10)
    assert df.empty

def test_profit_target_inference_initialization(mock_database):
    """Test that ProfitTargetInference can be initialized."""
    inference = ProfitTargetInference(database=mock_database)
    assert inference.database is mock_database
    assert isinstance(inference.models, dict)
    assert isinstance(inference.encoders, dict)
    assert isinstance(inference.features, dict)

def test_profit_target_inference_fallback(mock_database):
    """Test that inference returns fallback values when no model is loaded."""
    inference = ProfitTargetInference(database=mock_database)

    # Without models, should return default multipliers
    baseline_mult = inference.predict_profit_target_multiplier(
        symbol='TEST',
        components={},
        target_date='2026-01-01',
        strategy='baseline'
    )
    assert baseline_mult == 3.0  # Default baseline multiplier

    mr_mult = inference.predict_profit_target_multiplier(
        symbol='TEST',
        components={},
        target_date='2026-01-01',
        strategy='mean_reversion'
    )
    assert mr_mult == 2.0  # Default mean reversion multiplier

def test_calculate_baseline_setup_with_profit_multiplier(base_data, mock_database):
    """Test that calculate_baseline_setup accepts ml_profit_multiplier parameter."""
    from bluehorseshoe.analysis.strategy import SwingTrader

    trader = SwingTrader(database=mock_database)
    df = base_data.copy()

    # Test with custom profit multiplier
    setup = trader.calculate_baseline_setup(df, ml_stop_multiplier=2.0, ml_profit_multiplier=4.5)

    assert 'take_profit' in setup
    assert 'entry_price' in setup
    assert 'stop_loss' in setup
    assert setup['take_profit'] > setup['entry_price']

def test_calculate_mr_setup_with_profit_multiplier(base_data, mock_database):
    """Test that calculate_mean_reversion_setup accepts ml_profit_multiplier parameter."""
    from bluehorseshoe.analysis.strategy import SwingTrader

    trader = SwingTrader(database=mock_database)
    df = base_data.copy()

    # Test with custom profit multiplier
    setup = trader.calculate_mean_reversion_setup(df, ml_stop_multiplier=1.5, ml_profit_multiplier=2.5)

    assert 'take_profit' in setup
    assert 'entry_price' in setup
    assert 'stop_loss' in setup
    assert setup['take_profit'] > setup['entry_price']
