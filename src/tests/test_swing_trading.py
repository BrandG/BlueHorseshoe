"""
Unit tests for the SwingTrader and TechnicalAnalyzer classes in the swing_trading module.

This module contains the following tests:
- test_calculate_trend: Tests the calculate_trend method of the TechnicalAnalyzer class.
- test_calculate_entry_price: Tests the calculate_entry_price method of the SwingTrader class.
- test_calculate_technical_score: Tests the calculate_technical_score method of the TechnicalAnalyzer class.
- test_process_symbol: Tests the process_symbol method of the SwingTrader class.

Fixtures:
- sample_data: Generates a sample DataFrame with synthetic stock trading data for the past 30 days.
- swing_trader: Creates and returns an instance of the SwingTrader class.
"""

import pytest
import pandas as pd
from bluehorseshoe.analysis.strategy import SwingTrader, TechnicalAnalyzer

@pytest.fixture
def sample_data():
    """
    Generates a sample DataFrame with synthetic stock trading data for the past 30 days.

    Returns:
        pd.DataFrame: A DataFrame containing the following columns:
            - date (Timestamp): The date of the trading data.
            - open (float): The opening price of the stock.
            - high (float): The highest price of the stock.
            - low (float): The lowest price of the stock.
            - close (float): The closing price of the stock.
            - volume (int): The trading volume of the stock.
            - avg_volume_20 (int): The average trading volume over the past 20 days.
            - dmi_p (float): The positive directional movement index.
            - dmi_n (float): The negative directional movement index.
            - adx (float): The average directional index.
            - macd_line (float): The MACD line value.
            - macd_signal (float): The MACD signal line value.
            - rsi_14 (float): The 14-day relative strength index.
            - roc_5 (float): The 5-day rate of change.
            - bb_lower (float): The lower Bollinger Band value.
            - bb_upper (float): The upper Bollinger Band value.
            - stoch_k (float): The stochastic %K value.
            - stoch_d (float): The stochastic %D value.
    """
    df = pd.DataFrame([{
            'date': pd.Timestamp.now().normalize() - pd.Timedelta(days=30-i),
            'open': 1.5 * i,
            'high': 1.5 * i,
            'low': 1.5 * i,
            'close': 1.5 * i,
            'volume': 100000 * i,
            'avg_volume_20': 100000 * i,
            'dmi_p': 25 * i,
            'dmi_n': 20 * i,
            'adx': 30 * i,
            'macd_line': 1 * i,
            'macd_signal': 0.5 * i,
            'rsi_14': 50 * i,
            'roc_5': 0.5 * i,
            'bb_lower': 8 * i,
            'bb_upper': 12 * i,
            'stoch_k': 80 * i,
            'stoch_d': 80 * i,
        } for i in range(30)])
    return df

@pytest.fixture
def swing_trader():
    """
    Create and return an instance of the SwingTrader class.

    Returns:
        SwingTrader: An instance of the SwingTrader class.
    """
    return SwingTrader()

def test_calculate_trend(sample_data): # pylint: disable=redefined-outer-name
    """
    Test the calculate_trend method of the TechnicalAnalyzer class.

    Args:
        sample_data (list): A list of sample data points to analyze.

    Asserts:
        The trend calculated by the TechnicalAnalyzer is "Strong Uptrend".
    """
    trend = TechnicalAnalyzer.calculate_trend(sample_data)
    assert trend == "Strong Uptrend"

def test_calculate_entry_price(swing_trader, sample_data): # pylint: disable=redefined-outer-name
    """
    Test the calculate_entry_price method of the SwingTrader class.

    This test verifies that the entry price calculated by the SwingTrader
    is 5% higher than the closing price of the last data point in the
    sample_data.

    Args:
        swing_trader (SwingTrader): An instance of the SwingTrader class.
        sample_data (pd.DataFrame): A DataFrame containing sample trading data.

    Asserts:
        The calculated entry price is 5% higher than the closing price of
        the last data point in the sample_data.
    """
    entry_price = swing_trader.calculate_entry_price(sample_data)
    assert entry_price == sample_data.iloc[-1]['close'] * 1.05

def test_calculate_technical_score(sample_data):  # pylint: disable=redefined-outer-name
    """
    Test the calculate_technical_score method of the TechnicalAnalyzer class.

    Args:
        sample_data (dict): A dictionary containing sample stock data.

    Asserts:
        The calculated technical score for the given data is greater than 0.
    """
    score = TechnicalAnalyzer.calculate_technical_score(sample_data)
    assert score > 0

def test_process_symbol(swing_trader, sample_data, mocker): # pylint: disable=redefined-outer-name
    """
    Test the process_symbol method of the swing_trader object.

    This test mocks the load_historical_data function, GlobalData, and the current timestamp to ensure
    the process_symbol method processes the symbol 'IBM' correctly.

    Args:
        swing_trader (SwingTrader): An instance of the SwingTrader class.
        sample_data (pd.DataFrame): A sample DataFrame containing historical data.
        mocker (pytest_mock.MockerFixture): A fixture for mocking objects.

    Asserts:
        The result is not None.
        The result's symbol is 'IBM'.
        The result's name is 'Test Stock'.
        The result's entry_price is greater than 0.
        The result's stop_loss is greater than 0.
        The result's take_profit is greater than 0.
        The result's score is greater than 0.
    """
    mocker.patch('bluehorseshoe.analysis.strategy.load_historical_data', return_value={'days': sample_data.to_dict('records'),
                                                                     'symbol':'IBM', 'full_name': 'Test Stock'})
    mocker.patch('bluehorseshoe.analysis.strategy.GlobalData', holiday=False)
    mocker.patch('bluehorseshoe.analysis.strategy.pd.Timestamp.now', return_value=pd.Timestamp.now().normalize())

    result = swing_trader.process_symbol('IBM')
    assert result is not None
    assert result['symbol'] == 'IBM'
    assert result['name'] == 'Test Stock'
    assert result['entry_price'] > 0
    assert result['stop_loss'] > 0
    assert result['take_profit'] > 0
    assert result['score'] > 0