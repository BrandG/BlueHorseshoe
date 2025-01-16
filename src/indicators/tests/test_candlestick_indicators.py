"""
Module for testing candlestick indicators.

This module contains unit tests for the `CandlestickIndicator` class, which provides methods to detect various candlestick patterns in financial data.

Functions:
    sample_data(): Fixture that provides sample data for testing.
    test_is_white_candle(): Tests the `_is_white_candle` method of `CandlestickIndicator`.
    test_has_small_shadow(): Tests the `_has_small_shadow` method of `CandlestickIndicator`.
    test_is_higher_open(): Tests the `_is_higher_open` method of `CandlestickIndicator`.
    test_detect_three_white_soldiers(sample_data): Tests the `_detect_three_white_soldiers` method of `CandlestickIndicator`.
    test_find_rise_fall_3_methods(sample_data): Tests the `find_rise_fall_3_methods` method of `CandlestickIndicator`.
    test_find_marubozu(sample_data): Tests the `find_marubozu` method of `CandlestickIndicator`.
    test_find_belt_hold(sample_data): Tests the `find_belt_hold` method of `CandlestickIndicator`.
    test_calculate_score(sample_data): Tests the `calculate_score` method of `CandlestickIndicator`.
"""
import sys
import pandas as pd
from src.indicators.indicator import IndicatorScore  # pylint: disable=import-error
sys.path.append('/workspaces/BlueHorseshoe/src')
from indicators.candlestick_indicators import CandlestickIndicator # pylint: disable=wrong-import-position

def sample_data():
    """
    Generates a sample DataFrame with candlestick data.

    The DataFrame contains 30 rows with columns 'open', 'high', 'low', and 'close',
    where each row represents a candlestick with identical values for open, high, low, and close.

    Returns:
        pd.DataFrame: A DataFrame with 30 rows and 4 columns ('open', 'high', 'low', 'close'),
                      with each value being a float.
    """
    df = pd.DataFrame([
    { 'open': 1, 'high': 1, 'low': 1, 'close': 1 },
    { 'open': 2, 'high': 2, 'low': 2, 'close': 2 },
    { 'open': 3, 'high': 3, 'low': 3, 'close': 3 },
    { 'open': 4, 'high': 4, 'low': 4, 'close': 4 },
    { 'open': 5, 'high': 5, 'low': 5, 'close': 5 },
    { 'open': 6, 'high': 6, 'low': 6, 'close': 6 },
    { 'open': 7, 'high': 7, 'low': 7, 'close': 7 },
    { 'open': 8, 'high': 8, 'low': 8, 'close': 8 },
    { 'open': 9, 'high': 9, 'low': 9, 'close': 9 },
    { 'open': 10, 'high': 10, 'low': 10, 'close': 10 },
    { 'open': 11, 'high': 11, 'low': 11, 'close': 11 },
    { 'open': 12, 'high': 12, 'low': 12, 'close': 12 },
    { 'open': 13, 'high': 13, 'low': 13, 'close': 13 },
    { 'open': 14, 'high': 14, 'low': 14, 'close': 14 },
    { 'open': 15, 'high': 15, 'low': 15, 'close': 15 },
    { 'open': 16, 'high': 16, 'low': 16, 'close': 16 },
    { 'open': 17, 'high': 17, 'low': 17, 'close': 17 },
    { 'open': 18, 'high': 18, 'low': 18, 'close': 18 },
    { 'open': 19, 'high': 19, 'low': 19, 'close': 19 },
    { 'open': 20, 'high': 20, 'low': 20, 'close': 20 },
    { 'open': 21, 'high': 21, 'low': 21, 'close': 21 },
    { 'open': 22, 'high': 22, 'low': 22, 'close': 22 },
    { 'open': 23, 'high': 23, 'low': 23, 'close': 23 },
    { 'open': 24, 'high': 24, 'low': 24, 'close': 24 },
    { 'open': 25, 'high': 25, 'low': 25, 'close': 25 },
    { 'open': 26, 'high': 26, 'low': 26, 'close': 26 },
    { 'open': 27, 'high': 27, 'low': 27, 'close': 27 },
    { 'open': 28, 'high': 28, 'low': 28, 'close': 28 },
    { 'open': 29, 'high': 29, 'low': 29, 'close': 29 },
    { 'open': 30, 'high': 30, 'low': 30, 'close': 30 }
    ])
    return df.astype(float)

def test_is_white_candle():
    """
    Test the _is_white_candle method of the CandlestickIndicator class.

    This test verifies that the _is_white_candle method correctly identifies
    white candles (where the closing price is higher than the opening price).

    Test cases:
    - When the opening price is 1.0 and the closing price is 1.1, the result should be True.
    - When the opening price is 1.1 and the closing price is 1.0, the result should be False.
    - When the opening price is 1.0 and the closing price is 1.0, the result should be False.
    """
    # Create an instance to test protected methods
    indicator = CandlestickIndicator(sample_data())
    assert indicator.is_white_candle(1.0, 1.1) is True
    assert indicator.is_white_candle(1.1, 1.0) is False
    assert indicator.is_white_candle(1.0, 1.0) is False

def test_has_small_shadow():
    """
    Test the _has_small_shadow method of the CandlestickIndicator class.

    This test checks if the _has_small_shadow method correctly identifies
    whether a candlestick has a small shadow based on the given parameters.

    Test Cases:
    - Case 1: Open=1.0, High=1.2, Low=0.8, Close=1.05
      Expected Result: False (The shadow is not small)
    - Case 2: Open=4.0, High=4.01, Low=1.98, Close=2.0
      Expected Result: True (The shadow is small)
    """
    indicator = CandlestickIndicator(sample_data())
    assert indicator.has_small_shadow(1.0, 1.2, 0.8, 1.05) is False
    assert indicator.has_small_shadow(4.0, 4.01, 1.98, 2.0) is True

def test_is_higher_open():
    """
    Test the _is_higher_open method of the CandlestickIndicator class.

    This test checks if the _is_higher_open method correctly identifies
    whether the open price of a candlestick is higher than a given value.

    Assertions:
        - When the first argument is less than the second, the method should return True.
        - When the first argument is greater than or equal to the second, the method should return False.
    """
    indicator = CandlestickIndicator(sample_data())
    assert indicator.is_higher_open(1.0, 1.1) is True
    assert indicator.is_higher_open(1.1, 1.0) is False

def test_detect_three_white_soldiers():
    """
    Test the detection of the 'Three White Soldiers' candlestick pattern.

    This test initializes a CandlestickIndicator with sample data and asserts
    that the _detect_three_white_soldiers method returns 0.0, indicating that
    the pattern is not detected in the provided sample data.
    """
    indicator = CandlestickIndicator(sample_data())
    assert indicator.detect_three_white_soldiers() == 0.0

def test_find_rise_fall_3_methods():
    """
    Test the `find_rise_fall_3_methods` method of the `CandlestickIndicator` class.

    This test initializes a `CandlestickIndicator` object with `sample_data` and asserts that
    the `find_rise_fall_3_methods` method returns 0.0.

    The `find_rise_fall_3_methods` method is expected to analyze the candlestick patterns
    in the provided data and determine if there is a rise or fall according to three different
    methods.

    Assertions:
        - The method should return 0.0 when called with the provided `sample_data`.
    """
    indicator = CandlestickIndicator(sample_data())
    assert indicator.find_rise_fall_3_methods() == 0.0

def test_find_marubozu():
    """
    Test the find_marubozu method of the CandlestickIndicator class.

    This test initializes a CandlestickIndicator object with sample data
    and asserts that the find_marubozu method returns 0.0.

    Returns:
        None
    """
    indicator = CandlestickIndicator(sample_data())
    assert indicator.find_marubozu() == 0.0

def test_find_belt_hold():
    """
    Test the find_belt_hold method of the CandlestickIndicator class.

    This test initializes a CandlestickIndicator object with sample data and 
    asserts that the find_belt_hold method returns 0.0.

    Returns:
        None
    """
    indicator = CandlestickIndicator(sample_data())
    assert indicator.find_belt_hold() == 0.0

def test_calculate_score():
    """
    Test the calculate_score method of the CandlestickIndicator class.

    This test initializes a CandlestickIndicator object with sample_data
    and asserts that the calculate_score method returns 0.0.
    """
    indicator = CandlestickIndicator(sample_data())
    assert indicator.get_score() == IndicatorScore(buy=0.0, sell=0.0)
