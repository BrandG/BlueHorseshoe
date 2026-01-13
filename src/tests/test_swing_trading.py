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
from bluehorseshoe.analysis.strategy import SwingTrader, TechnicalAnalyzer, StrategyContext

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
            'open': 100 + (1.5 * i),
            'high': 105 + (1.5 * i),
            'low': 95 + (1.5 * i),
            'close': 100 + (1.5 * i),
            'volume': 1000000 + (100 * i),
            'avg_volume_20': 1000000,
            'dmi_p': 25,
            'dmi_n': 20,
            'adx': 30,
            'macd_line': 1,
            'macd_signal': 0.5,
            'rsi_14': 50,
            'roc_5': 0.5,
            'bb_lower': 90 + (1.5 * i),
            'bb_upper': 110 + (1.5 * i),
            'stoch_k': 80,
            'stoch_d': 80,
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

def test_calculate_baseline_setup(swing_trader, sample_data): # pylint: disable=redefined-outer-name

    """

    Test the calculate_baseline_setup method of the SwingTrader class.

    """

    setup = swing_trader.calculate_baseline_setup(sample_data)

    assert setup['entry_price'] > 0

    assert setup['stop_loss'] < setup['entry_price']

    assert setup['take_profit'] > setup['entry_price']

    assert setup['rr_ratio'] > 0



def test_calculate_technical_score(sample_data):  # pylint: disable=redefined-outer-name

    """

    Test the calculate_technical_score method of the TechnicalAnalyzer class.

    """

    score = TechnicalAnalyzer.calculate_technical_score(sample_data)

    assert score['total'] > 0



def test_process_symbol(swing_trader, sample_data, mocker): # pylint: disable=redefined-outer-name
    """
    Test the process_symbol method of the swing_trader object.
    """
    mocker.patch('bluehorseshoe.analysis.strategy.load_historical_data', return_value={'days': sample_data.to_dict('records'),
                                                                     'symbol':'IBM', 'full_name': 'Test Stock'})
    mocker.patch('bluehorseshoe.analysis.strategy.GlobalData', holiday=False)
    mocker.patch('bluehorseshoe.analysis.strategy.MIN_RR_RATIO', 0.0)

    # Mocking now to a Sunday so BDay(1) is Friday (Jan 2)
    mocker.patch('bluehorseshoe.analysis.strategy.pd.Timestamp.now', return_value=pd.Timestamp('2026-01-04'))

    # Adjust sample data to have Jan 2 as the last date to match BDay(1) from Jan 4
    adjusted_data = sample_data.copy()
    last_trading_day = pd.Timestamp('2026-01-04').normalize() - pd.offsets.BDay(1)
    # Re-calculate dates so the last one is last_trading_day
    for i in range(len(adjusted_data)):
        adjusted_data.loc[i, 'date'] = last_trading_day - pd.Timedelta(days=len(adjusted_data)-1-i)

    mocker.patch('bluehorseshoe.analysis.strategy.load_historical_data', return_value={'days': adjusted_data.to_dict('records'),
                                                                     'symbol':'IBM', 'full_name': 'Test Stock'})

    ctx = StrategyContext()
    result = swing_trader.process_symbol('IBM', ctx)
    assert result is not None
    assert result['symbol'] == 'IBM'
    assert result['name'] == 'Test Stock'
    assert result['baseline_setup']['entry_price'] > 0
    assert result['baseline_score'] > 0
