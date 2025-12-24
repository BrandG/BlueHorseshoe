"""Volume Indicator Tests Module

This module contains test cases for the VolumeIndicator class, which calculates 
various volume-based technical indicators and scores for financial market data.

The tests verify the functionality of:
- ATR (Average True Range) spike detection
- ATR band scoring  
- Average volume calculations
- Chaikin Money Flow (CMF) indicator
- On Balance Volume (OBV) trend scoring
- Overall volume score calculation

Test data is provided via a fixture that generates a sample DataFrame with 
synthetic price and volume data. The data consists of 25 periods where prices
increment linearly and volume remains constant.

Test Fixtures:
    sample_data: Generates DataFrame with OHLCV data for testing

Dependencies:
    - pandas 
    - pytest
    - bluehorseshoe.analysis.indicators.volume_indicators.VolumeIndicator
"""

from collections import namedtuple
import pandas as pd
from bluehorseshoe.analysis.indicators.volume_indicators import VolumeIndicator

Score = namedtuple('Score', ['buy', 'sell'])

def sample_data() -> pd.DataFrame:
    """
    Generate a sample pandas DataFrame with financial market data.

    The DataFrame contains 25 rows of mock trading data with consistent values
    where the numerical value increases by 1 for each row from 1 to 25.

    Returns:
        pd.DataFrame: A DataFrame with the following columns:
            - open (float): Opening price for each period
            - high (float): Highest price for each period
            - low (float): Lowest price for each period
            - close (float): Closing price for each period
            - volume (int): Trading volume (constant at 100001)
    """
    return pd.DataFrame([
    { 'open': 1, 'high': 1, 'low': 1, 'close': 1, 'volume': 100001 },
    { 'open': 2, 'high': 2, 'low': 2, 'close': 2, 'volume': 100001 },
    { 'open': 3, 'high': 3, 'low': 3, 'close': 3, 'volume': 100001 },
    { 'open': 4, 'high': 4, 'low': 4, 'close': 4, 'volume': 100001 },
    { 'open': 5, 'high': 5, 'low': 5, 'close': 5, 'volume': 100001 },
    { 'open': 6, 'high': 6, 'low': 6, 'close': 6, 'volume': 100001 },
    { 'open': 7, 'high': 7, 'low': 7, 'close': 7, 'volume': 100001 },
    { 'open': 8, 'high': 8, 'low': 8, 'close': 8, 'volume': 100001 },
    { 'open': 9, 'high': 9, 'low': 9, 'close': 9, 'volume': 100001 },
    { 'open': 10, 'high': 10, 'low': 10, 'close': 10, 'volume': 100001 },
    { 'open': 11, 'high': 11, 'low': 11, 'close': 11, 'volume': 100001 },
    { 'open': 12, 'high': 12, 'low': 12, 'close': 12, 'volume': 100001 },
    { 'open': 13, 'high': 13, 'low': 13, 'close': 13, 'volume': 100001 },
    { 'open': 14, 'high': 14, 'low': 14, 'close': 14, 'volume': 100001 },
    { 'open': 15, 'high': 15, 'low': 15, 'close': 15, 'volume': 100001 },
    { 'open': 16, 'high': 16, 'low': 16, 'close': 16, 'volume': 100001 },
    { 'open': 17, 'high': 17, 'low': 17, 'close': 17, 'volume': 100001 },
    { 'open': 18, 'high': 18, 'low': 18, 'close': 18, 'volume': 100001 },
    { 'open': 19, 'high': 19, 'low': 19, 'close': 19, 'volume': 100001 },
    { 'open': 20, 'high': 20, 'low': 20, 'close': 20, 'volume': 100001 },
    { 'open': 21, 'high': 21, 'low': 21, 'close': 21, 'volume': 100001 },
    { 'open': 22, 'high': 22, 'low': 22, 'close': 22, 'volume': 100001 },
    { 'open': 23, 'high': 23, 'low': 23, 'close': 23, 'volume': 100001 },
    { 'open': 24, 'high': 24, 'low': 24, 'close': 24, 'volume': 100001 },
    { 'open': 25, 'high': 25, 'low': 25, 'close': 25, 'volume': 100001 },
    ])

def test_score_atr_spike():
    """Test the score_atr_spike method of VolumeIndicator.

    This test verifies that the score_atr_spike() method correctly calculates 
    the ATR spike score for the given sample data.

    Args:
        sample_data (pd.DataFrame): Sample market data containing price and volume information

    Returns:
        None

    Raises:
        AssertionError: If the calculated ATR spike score does not match expected value
    """
    vi = VolumeIndicator(sample_data())
    result = vi.score_atr_spike()
    expected_result = 0.0  # Update this value based on the expected result
    assert result == expected_result, f"Expected {expected_result}, but got {result}"

def test_score_atr_band():
    """
    Test the calculation of ATR band score.

    This test function verifies that the score_atr_band method of VolumeIndicator
    correctly calculates the ATR band score based on the sample data.

    Args:
        sample_data (pd.DataFrame): A fixture containing sample price and volume data
            required for ATR band calculation.

    Returns:
        None

    Raises:
        AssertionError: If the calculated ATR band score does not match the expected value.
    """
    vi = VolumeIndicator(sample_data())
    result = vi.score_atr_band()
    expected_result = -1.0  # Update this value based on the expected result
    assert result == expected_result, f"Expected {expected_result}, but got {result}"

def test_calculate_avg_volume():
    """Test the calculation of average volume.

    This test verifies that the VolumeIndicator.calculate_avg_volume method correctly
    calculates the average trading volume from the sample data.

    Args:
        sample_data (pd.DataFrame): Fixture providing sample price and volume data.

    Returns:
        None

    Raises:
        AssertionError: If the calculated average volume doesn't match the expected value.
    """
    vi = VolumeIndicator(sample_data())
    result = vi.calculate_avg_volume()
    expected_result = 1.0  # Update this value based on the expected result
    assert result == expected_result, f"Expected {expected_result}, but got {result}"

def test_calculate_cmf_with_ta():
    """
    Test the calculation of Chaikin Money Flow (CMF) using the TA library.

    This test function verifies that the calculate_cmf_with_ta method in the VolumeIndicator
    class correctly calculates the Chaikin Money Flow indicator using the TA library implementation.

    Args:
        sample_data (pd.DataFrame): Fixture providing sample price and volume data for testing.
            Expected to contain OHLCV (Open, High, Low, Close, Volume) data.

    Returns:
        None

    Raises:
        AssertionError: If the calculated CMF value doesn't match the expected result.

    Note:
        The expected result value (-1.0) should be updated based on the actual expected
        output for the given sample data.
    """
    vi = VolumeIndicator(sample_data())
    result = vi.calculate_cmf_with_ta()
    expected_result = -1.0  # Update this value based on the expected result
    assert result == expected_result, f"Expected {expected_result}, but got {result}"

def test_score_obv_trend():
    """
    Test function for score_obv_trend method in VolumeIndicator class.

    Tests the calculation of the On Balance Volume (OBV) trend score based on
    sample data. OBV trend scoring measures volume flow momentum to indicate
    potential price movements.

    Args:
        sample_data (pd.DataFrame): Fixture containing OHLCV sample data for testing

    Returns:
        None

    Raises:
        AssertionError: If calculated OBV trend score doesn't match expected value
    """
    vi = VolumeIndicator(sample_data())
    result = vi.score_obv_trend()
    expected_result = 0.0  # Update this value based on the expected result
    assert result == expected_result, f"Expected {expected_result}, but got {result}"

def test_calculate_score():
    """Test the calculate_score method of the VolumeIndicator class.

    Tests if the calculate_score method returns the expected volume score calculation 
    based on the sample data provided.

    Args:
        sample_data (pd.DataFrame): Fixture providing sample price/volume data

    Returns:
        None

    Raises:
        AssertionError: If the calculated score does not match the expected result
    """
    vi = VolumeIndicator(sample_data())
    result = vi.get_score()
    expected_result = Score(buy=-1.0, sell=0)  # Update this value based on the expected result
    assert result == expected_result, f"Expected {expected_result}, but got {result}"