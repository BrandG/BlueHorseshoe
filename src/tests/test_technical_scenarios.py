"""
Tests for technical analysis scenarios.
"""
# pylint: disable=redefined-outer-name
import pytest
import pandas as pd
from bluehorseshoe.analysis.technical_analyzer import TechnicalAnalyzer

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
        "macd_signal": [0.0] * 30
    })

def test_baseline_score(base_data):
    """Tests the baseline score calculation."""
    scores = TechnicalAnalyzer.calculate_technical_score(base_data)
    # Baseline total can be 0.0 if no indicators trigger
    assert "total" in scores
    assert scores.get("penalty_rsi") == 0.0
    assert scores.get("bonus_oversold_rsi") == 0.0

def test_rsi_oversold_extreme(base_data):
    """Verify RSI < 30 gives a -5.0 reward."""
    data = base_data.copy()
    data.loc[data.index[-1], 'rsi_14'] = 25.0
    scores = TechnicalAnalyzer.calculate_technical_score(data)
    assert scores['bonus_oversold_rsi'] == -5.0

def test_rsi_oversold_moderate(base_data):
    """Verify RSI between 30 and 35 gives a -2.0 reward."""
    data = base_data.copy()
    data.loc[data.index[-1], 'rsi_14'] = 32.0
    scores = TechnicalAnalyzer.calculate_technical_score(data)
    assert scores['bonus_oversold_rsi'] == -2.0

def test_bb_oversold(base_data):
    """Verify price below lower Bollinger Band gives a -3.0 reward."""
    data = base_data.copy()
    data.loc[data.index[-1], 'close'] = 85.0 # Lower than bb_lower (90.0)
    scores = TechnicalAnalyzer.calculate_technical_score(data)
    assert scores['bonus_oversold_bb'] == -3.0

def test_ema_overextension(base_data):
    """Verify price > 12% above EMA9 gives an extreme penalty."""
    data = base_data.copy()
    # To make close > 1.12 * EMA9, we need to push the last close high
    # Baseline is all 100. EMA9 will be ~100.
    data.loc[data.index[-1], 'close'] = 120.0 # ~20% above
    scores = TechnicalAnalyzer.calculate_technical_score(data)
    assert scores['penalty_ema_overextension'] == -7.0

def test_rsi_overbought(base_data):
    """Verify RSI > 75 gives an extreme penalty."""
    data = base_data.copy()
    data.loc[data.index[-1], 'rsi_14'] = 80.0
    scores = TechnicalAnalyzer.calculate_technical_score(data)
    assert scores['penalty_rsi'] == -5.0

def test_volume_exhaustion(base_data):
    """Verify volume > 3x average gives a penalty."""
    data = base_data.copy()
    data.loc[data.index[-1], 'volume'] = 1000000 # 5x baseline 200,000
    scores = TechnicalAnalyzer.calculate_technical_score(data)
    assert scores['penalty_volume_exhaustion'] == -3.0

def test_low_volume_early_exit(base_data):
    """Verify that low volume results in an early exit with 0.0 total."""
    data = base_data.copy()
    data.loc[data.index[-1], "avg_volume_20"] = 1000 # Below MIN_VOLUME_THRESHOLD (100,000)
    scores = TechnicalAnalyzer.calculate_technical_score(data)
    assert scores == {"total": 0.0}
