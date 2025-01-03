import pytest
import pandas as pd
from src.indicators.limit_indicators import LimitIndicator

@pytest.fixture
def sample_data():
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

def test_calculate_pivot_points(sample_data):
    indicator = LimitIndicator(sample_data)
    df = indicator.calculate_pivot_points()

    assert 'Pivot' in df.columns
    assert 'R1' in df.columns
    assert 'R2' in df.columns
    assert 'S1' in df.columns
    assert 'S2' in df.columns

def test_score_pivot_levels(sample_data):
    indicator = LimitIndicator(sample_data)
    score = indicator._score_pivot_levels()

    assert isinstance(score, float)

def test_score_52_week_range(sample_data):
    indicator = LimitIndicator(sample_data)
    score = indicator._score_52_week_range()

    assert isinstance(score, float)

def test_calculate_score(sample_data):
    indicator = LimitIndicator(sample_data)
    score = indicator.calculate_score()

    assert isinstance(score, float)