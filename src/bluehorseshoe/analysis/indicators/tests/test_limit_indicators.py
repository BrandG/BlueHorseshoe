"""
Unit tests for the LimitIndicator class.

This module contains test functions for verifying the functionality of the LimitIndicator
class methods. The tests cover calculation of pivot points, scoring of pivot levels,
52-week range scoring, and overall indicator score calculation.

The module uses a sample DataFrame with synthetic OHLC (Open, High, Low, Close) price 
data for testing purposes. The sample data consists of 30 rows where all OHLC values 
increment by 1 from 1 to 30.

Test Functions:
    - test_calculate_pivot_points: Tests pivot point level calculations
    - test_score_pivot_levels: Tests pivot level scoring
    - test_score_52_week_range: Tests 52-week range scoring
    - test_calculate_score: Tests overall indicator score calculation

Dependencies:
    - pandas
    - bluehorseshoe.analysis.indicators.limit_indicators.LimitIndicator
"""

from bluehorseshoe.analysis.indicators.indicator import IndicatorScore
from bluehorseshoe.analysis.indicators.limit_indicators import LimitIndicator
from bluehorseshoe.analysis.indicators.tests.test_candlestick_indicators import sample_data

def test_calculate_pivot_points():
    """
    Test the calculation of pivot points.

    This test function verifies that the calculate_pivot_points method of LimitIndicator
    correctly calculates and returns a DataFrame with the expected pivot point levels.

    The test checks for the presence of the following columns:
    - Pivot: The pivot point
    - R1: First resistance level
    - R2: Second resistance level
    - S1: First support level
    - S2: Second support level

    Returns:
        None

    Raises:
        AssertionError: If any of the expected columns are missing from the result DataFrame
    """
    indicator = LimitIndicator(sample_data())
    df = indicator.calculate_pivot_points()

    assert 'Pivot' in df.columns
    assert 'R1' in df.columns
    assert 'R2' in df.columns
    assert 'S1' in df.columns
    assert 'S2' in df.columns

def test_score_pivot_levels():
    """Tests score_pivot_levels method of LimitIndicator class.

    This test verifies that the score_pivot_levels method returns a float value
    representing the pivot levels score calculated from the sample data.

    Returns:
        None

    Raises:
        AssertionError: If returned score is not a float type
    """
    indicator = LimitIndicator(sample_data())
    score = indicator.score_pivot_levels()

    assert isinstance(score, float)

def test_score_52_week_range():
    """
    Test the score_52_week_range method of the LimitIndicator class.

    This test verifies that the score_52_week_range method returns a float value
    representing the stock's position within its 52-week trading range.

    Parameters
    ----------
    None

    Returns
    -------
    None

    Raises
    ------
    AssertionError
        If the returned score is not a float
    """
    indicator = LimitIndicator(sample_data())
    score = indicator.score_52_week_range()

    assert isinstance(score, float)

def test_calculate_score():
    """Test the calculation of a score by the LimitIndicator.

    This test function verifies that the calculate_score method of LimitIndicator
    returns a float value when provided with sample data.

    Returns:
        None

    Assertions:
        - The returned score is an instance of float
    """
    indicator = LimitIndicator(sample_data())
    assert indicator.get_score() == IndicatorScore(buy=2.0, sell=0.0)