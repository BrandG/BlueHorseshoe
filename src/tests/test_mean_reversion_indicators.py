"""
Tests for MeanReversionIndicator class.

Covers all 5 sub-indicators: RSI Divergence, Z-Score, Connors RSI, DV2, Short-Period ROC.
"""
# pylint: disable=redefined-outer-name

import numpy as np
import pandas as pd
import pytest

from bluehorseshoe.analysis.indicators.mean_reversion_indicators import MeanReversionIndicator


@pytest.fixture
def base_data():
    """60-row DataFrame with OHLCV + enrichment columns for MR indicators."""
    np.random.seed(42)
    n = 60
    dates = pd.date_range('2024-01-01', periods=n, freq='B')

    # Start at 100, random walk with slight downtrend for MR testing
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    high = close + np.abs(np.random.randn(n)) * 1.5
    low = close - np.abs(np.random.randn(n)) * 1.5
    open_price = close + np.random.randn(n) * 0.3
    volume = np.random.randint(100000, 500000, n).astype(float)

    df = pd.DataFrame({
        'date': dates,
        'open': open_price,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume,
    })

    # Enrichment columns
    df['rsi_14'] = 50 + np.random.randn(n) * 10  # Neutral RSI
    df['ema_20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['std_20'] = df['close'].rolling(20).std()
    df['roc_2'] = df['close'].pct_change(2) * 100
    df['roc_5'] = df['close'].pct_change(5) * 100
    df['rsi_3'] = 50 + np.random.randn(n) * 15
    df['dv2'] = ((df['close'] - df['low']) / (df['high'] - df['low'])).rolling(2).mean()
    df['bb_lower'] = df['ema_20'] - 2 * df['std_20']
    df['bb_upper'] = df['ema_20'] + 2 * df['std_20']
    df['stoch_k'] = 50 + np.random.randn(n) * 10
    df['stoch_d'] = 50 + np.random.randn(n) * 10
    df['avg_volume_20'] = df['volume'].rolling(20).mean()

    return df


# --- Z-Score Tests ---

def test_zscore_extreme_oversold(base_data):
    """Z-Score < -2.5 should return 3.0."""
    df = base_data.copy()
    # Push close far below EMA to get Z < -2.5
    ema = df['ema_20'].iloc[-1]
    std = df['std_20'].iloc[-1]
    df.loc[df.index[-1], 'close'] = ema - 3.0 * std

    indicator = MeanReversionIndicator(df)
    score = indicator.calculate_zscore()
    assert score == 3.0


def test_zscore_neutral(base_data):
    """Close near EMA should return 0.0."""
    df = base_data.copy()
    # Set close equal to EMA (Z = 0)
    df.loc[df.index[-1], 'close'] = df['ema_20'].iloc[-1]

    indicator = MeanReversionIndicator(df)
    score = indicator.calculate_zscore()
    assert score == 0.0


# --- DV2 Tests ---

def test_dv2_oversold(base_data):
    """DV2 < 0.1 should return 3.0."""
    df = base_data.copy()
    df.loc[df.index[-1], 'dv2'] = 0.05
    df.loc[df.index[-2], 'dv2'] = 0.05

    indicator = MeanReversionIndicator(df)
    score = indicator.calculate_dv2()
    assert score == 3.0


def test_dv2_neutral(base_data):
    """DV2 around 0.5 should return 0.0."""
    df = base_data.copy()
    df.loc[df.index[-1], 'dv2'] = 0.5

    indicator = MeanReversionIndicator(df)
    score = indicator.calculate_dv2()
    assert score == 0.0


# --- Short ROC Tests ---

def test_short_roc_moderate_drop(base_data):
    """ROC_2 = -4% should return 2.0."""
    df = base_data.copy()
    df.loc[df.index[-1], 'roc_2'] = -4.0

    indicator = MeanReversionIndicator(df)
    score = indicator.calculate_short_roc()
    assert score == 2.0


def test_short_roc_crash(base_data):
    """ROC_2 = -6% should return 3.0."""
    df = base_data.copy()
    df.loc[df.index[-1], 'roc_2'] = -6.0
    df.loc[df.index[-1], 'roc_5'] = -2.0  # Not deep enough for bonus

    indicator = MeanReversionIndicator(df)
    score = indicator.calculate_short_roc()
    assert score == 3.0


def test_short_roc_crash_with_bonus(base_data):
    """ROC_2 = -6% and ROC_5 < -5% should return 4.0 (3.0 + 1.0 bonus)."""
    df = base_data.copy()
    df.loc[df.index[-1], 'roc_2'] = -6.0
    df.loc[df.index[-1], 'roc_5'] = -6.0

    indicator = MeanReversionIndicator(df)
    score = indicator.calculate_short_roc()
    assert score == 4.0


# --- Connors RSI Tests ---

def test_connors_rsi_oversold(base_data):
    """Connors RSI with deeply oversold components should return positive score."""
    df = base_data.copy()
    # Make all components deeply oversold
    df['rsi_3'] = 5.0  # Very low RSI(3)
    # Create a strong down streak in close prices
    for i in range(len(df) - 10, len(df)):
        df.loc[df.index[i], 'close'] = df['close'].iloc[i - 1] - 1.0
    df['roc_2'] = -5.0  # Deep negative ROC

    indicator = MeanReversionIndicator(df)
    score = indicator.calculate_connors_rsi()
    assert score > 0


def test_connors_rsi_missing_columns(base_data):
    """Missing rsi_3 column should compute inline, not crash."""
    df = base_data.copy()
    df = df.drop(columns=['rsi_3', 'roc_2'], errors='ignore')

    indicator = MeanReversionIndicator(df)
    # Should not raise, returns some float
    score = indicator.calculate_connors_rsi()
    assert isinstance(score, float)


# --- RSI Divergence Tests ---

def test_rsi_divergence_present(base_data):
    """Bullish divergence (price lower low, RSI higher low) should return positive."""
    df = base_data.copy()

    # Create two clear swing lows in last 14 bars
    # First swing low at index -12: price=90, rsi=25
    # Second swing low at index -5: price=88, rsi=30 (lower price, higher RSI)
    idx = len(df)
    # Set up first swing low
    for offset in [-14, -13, -11, -10]:
        df.loc[df.index[idx + offset], 'close'] = 95
    df.loc[df.index[idx - 12], 'close'] = 90
    df.loc[df.index[idx - 12], 'rsi_14'] = 25

    # Set up second swing low
    for offset in [-7, -6, -4, -3]:
        df.loc[df.index[idx + offset], 'close'] = 93
    df.loc[df.index[idx - 5], 'close'] = 88
    df.loc[df.index[idx - 5], 'rsi_14'] = 32  # Higher RSI despite lower price

    # Fill recent bars
    for offset in [-2, -1]:
        df.loc[df.index[idx + offset], 'close'] = 92
        df.loc[df.index[idx + offset], 'rsi_14'] = 40

    indicator = MeanReversionIndicator(df)
    score = indicator.calculate_rsi_divergence()
    assert score > 0


def test_rsi_divergence_absent(base_data):
    """No divergence pattern should return 0.0."""
    df = base_data.copy()
    # Make close and RSI trend in same direction (no divergence)
    for i in range(len(df)):
        df.loc[df.index[i], 'rsi_14'] = 40 + i * 0.2

    indicator = MeanReversionIndicator(df)
    score = indicator.calculate_rsi_divergence()
    assert score == 0.0


# --- Aggregate Score Tests ---

def test_all_zero_weights(base_data):
    """With all weights at 0.0, buy_score should be 0.0."""
    indicator = MeanReversionIndicator(base_data, weight_category='mean_reversion_specific')
    result = indicator.get_score()
    assert result.buy == 0.0


def test_mr_weights_active(base_data):
    """With MR weights active and oversold conditions, buy_score should be positive."""
    df = base_data.copy()
    # Create oversold conditions
    ema = df['ema_20'].iloc[-1]
    std = df['std_20'].iloc[-1]
    df.loc[df.index[-1], 'close'] = ema - 2.5 * std  # Z-Score extreme
    df.loc[df.index[-1], 'dv2'] = 0.05  # DV2 oversold
    df.loc[df.index[-1], 'roc_2'] = -6.0  # Short ROC crash

    indicator = MeanReversionIndicator(df, weight_category='mr_mean_reversion_specific')
    result = indicator.get_score()
    assert result.buy > 0


# --- Integration Test ---

def test_integration_calculate_mean_reversion_score(base_data):
    """TechnicalAnalyzer.calculate_mean_reversion_score() should include new indicators."""
    from unittest.mock import MagicMock
    from bluehorseshoe.analysis.technical_analyzer import TechnicalAnalyzer

    df = base_data.copy()
    # Add remaining columns needed by TechnicalAnalyzer
    df['midpoint'] = (df['open'] + df['close']) / 2
    df['macd_line'] = 0.0
    df['macd_signal'] = 0.0
    df['macd_hist'] = 0.0
    df['adx'] = 25.0
    df['dmi_p'] = 20.0
    df['dmi_n'] = 15.0
    df['atr_14'] = 2.0
    df['bb_middle'] = df['ema_20']
    df['obv'] = df['volume'].cumsum()
    df['mfi'] = 50.0
    df['cci'] = 0.0
    df['willr'] = -50.0

    # Create oversold conditions so we get a positive MR-specific contribution
    ema = df['ema_20'].iloc[-1]
    std = df['std_20'].iloc[-1]
    df.loc[df.index[-1], 'close'] = ema - 2.5 * std
    df.loc[df.index[-1], 'dv2'] = 0.05
    df.loc[df.index[-1], 'roc_2'] = -6.0

    result = TechnicalAnalyzer._score_indicators(
        df,
        indicator_filters={'mean_reversion_specific': None},
        aggregation='sum',
        weight_prefix='mr_'
    )
    total_score, components, active_count = result
    assert active_count > 0
