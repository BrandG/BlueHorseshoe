"""Unit tests for the TrendIndicator class.

This module contains test cases for the TrendIndicator class methods,
including validation of required columns, calculation of various technical indicators
and their respective scores.

The test suite covers:
- Column validation
- PSAR (Parabolic Stop and Reverse) score calculation
- Ichimoku Cloud calculations and scoring
- Heiken Ashi calculations and scoring
- Overall trend score calculation

Test data includes a DataFrame with OHLC and stochastic indicator values
spanning 30 periods with incrementing values.

Classes:
    None (contains only test functions)

Functions:
    test_validate_columns: Tests column validation on initialization
    test_validate_columns_missing: Tests error handling for missing columns
    test_calculate_psar_score: Tests PSAR score calculation
    test_calculate_ichimoku: Tests Ichimoku Cloud component calculations
    test_calculate_ichimoku_score: Tests Ichimoku scoring
    test_calculate_heiken_ashi: Tests Heiken Ashi score calculation
    test_calculate_score: Tests overall trend score calculation
"""

import pandas as pd
from bluehorseshoe.analysis.indicators.indicator import IndicatorScore
from bluehorseshoe.analysis.indicators.trend_indicators import TrendIndicator

def sample_data() -> pd.DataFrame:
    """
    Generate a sample DataFrame with financial data for testing purposes.

    The DataFrame contains 30 rows with incrementing values from 1 to 30,
    where each row has the following columns:
    - open: Opening price
    - high: Highest price 
    - low: Lowest price
    - close: Closing price 
    - stoch_k: Stochastic oscillator %K value
    - stoch_d: Stochastic oscillator %D value

    Returns
    -------
    pandas.DataFrame
        A DataFrame containing sample financial data with all values as float type.
        Each column (open, high, low, close, stoch_k, stoch_d) contains values from 1 to 30.
    """
    data = [
    { 'open': 1, 'high': 1, 'low': 1, 'close': 1, 'stoch_k': 1, 'stoch_d': 1 },
    { 'open': 2, 'high': 2, 'low': 2, 'close': 2, 'stoch_k': 2, 'stoch_d': 2 },
    { 'open': 3, 'high': 3, 'low': 3, 'close': 3, 'stoch_k': 3, 'stoch_d': 3 },
    { 'open': 4, 'high': 4, 'low': 4, 'close': 4, 'stoch_k': 4, 'stoch_d': 4 },
    { 'open': 5, 'high': 5, 'low': 5, 'close': 5, 'stoch_k': 5, 'stoch_d': 5 },
    { 'open': 6, 'high': 6, 'low': 6, 'close': 6, 'stoch_k': 6, 'stoch_d': 6 },
    { 'open': 7, 'high': 7, 'low': 7, 'close': 7, 'stoch_k': 7, 'stoch_d': 7 },
    { 'open': 8, 'high': 8, 'low': 8, 'close': 8, 'stoch_k': 8, 'stoch_d': 8 },
    { 'open': 9, 'high': 9, 'low': 9, 'close': 9, 'stoch_k': 9, 'stoch_d': 9 },
    { 'open': 10, 'high': 10, 'low': 10, 'close': 10, 'stoch_k': 10, 'stoch_d': 10 },
    { 'open': 11, 'high': 11, 'low': 11, 'close': 11, 'stoch_k': 11, 'stoch_d': 11 },
    { 'open': 12, 'high': 12, 'low': 12, 'close': 12, 'stoch_k': 12, 'stoch_d': 12 },
    { 'open': 13, 'high': 13, 'low': 13, 'close': 13, 'stoch_k': 13, 'stoch_d': 13 },
    { 'open': 14, 'high': 14, 'low': 14, 'close': 14, 'stoch_k': 14, 'stoch_d': 14 },
    { 'open': 15, 'high': 15, 'low': 15, 'close': 15, 'stoch_k': 15, 'stoch_d': 15 },
    { 'open': 16, 'high': 16, 'low': 16, 'close': 16, 'stoch_k': 16, 'stoch_d': 16 },
    { 'open': 17, 'high': 17, 'low': 17, 'close': 17, 'stoch_k': 17, 'stoch_d': 17 },
    { 'open': 18, 'high': 18, 'low': 18, 'close': 18, 'stoch_k': 18, 'stoch_d': 18 },
    { 'open': 19, 'high': 19, 'low': 19, 'close': 19, 'stoch_k': 19, 'stoch_d': 19 },
    { 'open': 20, 'high': 20, 'low': 20, 'close': 20, 'stoch_k': 20, 'stoch_d': 20 },
    { 'open': 21, 'high': 21, 'low': 21, 'close': 21, 'stoch_k': 21, 'stoch_d': 21 },
    { 'open': 22, 'high': 22, 'low': 22, 'close': 22, 'stoch_k': 22, 'stoch_d': 22 },
    { 'open': 23, 'high': 23, 'low': 23, 'close': 23, 'stoch_k': 23, 'stoch_d': 23 },
    { 'open': 24, 'high': 24, 'low': 24, 'close': 24, 'stoch_k': 24, 'stoch_d': 24 },
    { 'open': 25, 'high': 25, 'low': 25, 'close': 25, 'stoch_k': 25, 'stoch_d': 25 },
    { 'open': 26, 'high': 26, 'low': 26, 'close': 26, 'stoch_k': 26, 'stoch_d': 26 },
    { 'open': 27, 'high': 27, 'low': 27, 'close': 27, 'stoch_k': 27, 'stoch_d': 27 },
    { 'open': 28, 'high': 28, 'low': 28, 'close': 28, 'stoch_k': 28, 'stoch_d': 28 },
    { 'open': 29, 'high': 29, 'low': 29, 'close': 29, 'stoch_k': 29, 'stoch_d': 29 },
    { 'open': 30, 'high': 30, 'low': 30, 'close': 30, 'stoch_k': 30, 'stoch_d': 30 }
    ]
    return pd.DataFrame(data)


def test_calculate_psar_score():
    """Test the calculation of PSAR (Parabolic Stop And Reverse) score.

    This test function verifies that the calculate_psar_score method returns a float value
    when provided with test data. The PSAR indicator is used to identify potential reversal
    points in market trends.

    Args:
        None

    Returns:
        None

    Raises:
        AssertionError: If the returned score is not a float

    Test Data:
        Uses test_data fixture defined in the test setup
    """
    indicator = TrendIndicator(sample_data())
    score = indicator.calculate_psar_score()
    assert isinstance(score, float)

def test_calculate_ichimoku():
    """Test the calculation of Ichimoku Cloud indicator.

    This test function verifies that the calculate_ichimoku method correctly calculates
    all components of the Ichimoku Cloud technical indicator:
    - Tenkan-sen (Conversion Line)
    - Kijun-sen (Base Line)
    - Senkou Span A (Leading Span A)
    - Senkou Span B (Leading Span B)
    - Chikou Span (Lagging Span)

    The test checks that the returned DataFrame contains all required columns for
    the Ichimoku Cloud calculation.

    Returns:
        None

    Raises:
        AssertionError: If any of the required Ichimoku components are missing from results
    """
    indicator = TrendIndicator(sample_data())
    result = indicator.calculate_ichimoku()
    assert 'tenkan' in result.columns
    assert 'kijun' in result.columns
    assert 'spanA' in result.columns
    assert 'spanB' in result.columns
    assert 'chikou' in result.columns

def test_calculate_ichimoku_score():
    """
    Test the calculation of the Ichimoku score.

    This function tests the calculate_ichimoku_score method of the TrendIndicator class.
    It ensures that the method returns a float value representing the Ichimoku score
    for the given test data.

    Returns:
        None

    Asserts:
        - The returned score is an instance of float
    """
    indicator = TrendIndicator(sample_data())
    score = indicator.calculate_ichimoku_score()
    assert isinstance(score, float)

def test_calculate_heiken_ashi():
    """Test the calculation of Heiken Ashi indicator score.

    This test function verifies that the calculate_heiken_ashi method 
    properly calculates a Heiken Ashi score from the provided test data 
    and returns a float value.

    Args:
        None

    Returns:
        None

    Raises:
        AssertionError: If the returned score is not a float
    """
    indicator = TrendIndicator(sample_data())
    score = indicator.calculate_heiken_ashi()
    assert isinstance(score, float)

def test_calculate_score():
    """
    Test the calculate_score method of TrendIndicator class.

    Tests that the method properly calculates and returns a score value based on the
    provided test data. The test verifies that the returned value is a float type.

    Returns:
        None
    """
    indicator = TrendIndicator(sample_data())
    score = indicator.get_score()
    assert isinstance(score, IndicatorScore), f"Expected type Score, but got {type(score)}"
    assert isinstance(score.buy, float), f"Expected type float for buy, but got {type(score.buy)}"
    assert isinstance(score.sell, float), f"Expected type float for sell, but got {type(score.sell)}"