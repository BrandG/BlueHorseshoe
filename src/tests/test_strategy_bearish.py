import pytest
import pandas as pd
from unittest.mock import MagicMock
from bluehorseshoe.analysis.strategy import SwingTrader, StrategyContext, TechnicalAnalyzer

@pytest.fixture
def sample_data():
    df = pd.DataFrame([{
            'date': pd.Timestamp.now().normalize() - pd.Timedelta(days=30-i),
            'open': 100.0 + i,
            'high': 101.0 + i, # Reduced volatility
            'low': 99.0 + i,   # Reduced volatility
            'close': 100.5 + i, # Uptrend
            'volume': 1000000.0,
            'avg_volume_20': 1000000.0,
            'ema_20': 100.0 + i,
            'dmi_p': 25.0,
            'dmi_n': 20.0,
            'adx': 30.0,
            'macd_line': 1.0,
            'macd_signal': 0.5,
            'rsi_14': 50.0,
            'roc_5': 0.5,
            'bb_lower': 90.0 + i,
            'bb_upper': 110.0 + i,
            'stoch_k': 80.0,
            'stoch_d': 80.0,
        } for i in range(30)])
    return df

def test_process_baseline_bearish_regime(sample_data, mocker):
    """
    Test that _process_baseline returns a result even in a Bearish regime
    after the filter was removed.
    """
    trader = SwingTrader()
    
    # Mock dependencies
    trader.ml_inference.predict_probability = MagicMock(return_value=0.6)
    
    # Context with Bearish regime
    ctx = StrategyContext(
        market_health={'status': 'Bearish', 'multiplier': 0.0}
    )
    
    # Since is_weekly_uptrend might fail on small sample, mock it or ensure sample is good.
    # The sample_data is strictly increasing, so it should pass uptrend check.
    
    # Call internal method
    last_row = sample_data.iloc[-1]
    result = trader._process_baseline(sample_data, "TEST", dict(last_row), ctx)
    
    assert result is not None
    assert result['score'] > 0
