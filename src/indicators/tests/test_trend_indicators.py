import pytest
import pandas as pd
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))
from src.indicators.trend_indicators import TrendIndicator

test_data = pd.DataFrame([
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
    ])

def test_validate_columns():
    indicator = TrendIndicator(test_data)
    assert indicator.validated

def test_validate_columns_missing():
    test_data = pd.DataFrame([
        { 'open': 1, 'low': 1, 'close': 1, 'stoch_k': 1, 'stoch_d': 1 },
        { 'open': 2, 'low': 2, 'close': 2, 'stoch_k': 2, 'stoch_d': 2 },
        { 'open': 3, 'low': 3, 'close': 3, 'stoch_k': 3, 'stoch_d': 3 },
        { 'open': 4, 'low': 4, 'close': 4, 'stoch_k': 4, 'stoch_d': 4 }])

    with pytest.raises(ValueError):
        TrendIndicator(test_data)

def test_calculate_psar_score():
    score = TrendIndicator._calculate_psar_score(test_data)
    assert isinstance(score, float)

def test_calculate_ichimoku():
    result = TrendIndicator._calculate_ichimoku(test_data)
    assert 'tenkan' in result.columns
    assert 'kijun' in result.columns
    assert 'spanA' in result.columns
    assert 'spanB' in result.columns
    assert 'chikou' in result.columns

def test_calculate_ichimoku_score():
    indicator = TrendIndicator(test_data)
    score = indicator._calculate_ichimoku_score(test_data)
    assert isinstance(score, float)

def test_calculate_heiken_ashi():
    indicator = TrendIndicator(test_data)
    score = indicator._calculate_heiken_ashi(test_data)
    assert isinstance(score, float)

def test_calculate_score():
    indicator = TrendIndicator(test_data)
    score = indicator.calculate_score()
    assert isinstance(score, float)