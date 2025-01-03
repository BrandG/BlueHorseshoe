import pytest
import pandas as pd
from src.indicators.moving_average_indicators import MovingAverageIndicator

@pytest.fixture
def sample_data():
    df = pd.DataFrame([
    { 'volume': 1, 'close': 1 },
    { 'volume': 2, 'close': 2 },
    { 'volume': 3, 'close': 3 },
    { 'volume': 4, 'close': 4 },
    { 'volume': 5, 'close': 5 },
    { 'volume': 6, 'close': 6 },
    { 'volume': 7, 'close': 7 },
    { 'volume': 8, 'close': 8 },
    { 'volume': 9, 'close': 9 },
    { 'volume': 10, 'close': 10 },
    { 'volume': 11, 'close': 11 },
    { 'volume': 12, 'close': 12 },
    { 'volume': 13, 'close': 13 },
    { 'volume': 14, 'close': 14 },
    { 'volume': 15, 'close': 15 },
    { 'volume': 16, 'close': 16 },
    { 'volume': 17, 'close': 17 },
    { 'volume': 18, 'close': 18 },
    { 'volume': 19, 'close': 19 },
    { 'volume': 20, 'close': 20 },
    { 'volume': 21, 'close': 21 },
    { 'volume': 22, 'close': 22 },
    { 'volume': 23, 'close': 23 },
    { 'volume': 24, 'close': 24 },
    { 'volume': 25, 'close': 25 },
    { 'volume': 26, 'close': 26 },
    { 'volume': 27, 'close': 27 },
    { 'volume': 28, 'close': 28 },
    { 'volume': 29, 'close': 29 },
    { 'volume': 30, 'close': 30 }
    ])
    return df.astype(float)

def test_calculate_wma(sample_data):
    indicator = MovingAverageIndicator(sample_data)
    wma = indicator.calculate_wma()
    assert len(wma) == len(sample_data)
    assert wma.isna().sum() == 19  # First 19 values should be NaN due to window size

def test_calculate_vwma(sample_data):
    indicator = MovingAverageIndicator(sample_data)
    vwma = indicator.calculate_vwma()
    assert len(vwma) == len(sample_data)
    assert vwma.isna().sum() == 19  # First 19 values should be NaN due to window size

def test_calculate_ma_score(sample_data):
    indicator = MovingAverageIndicator(sample_data)
    score = indicator.calculate_ma_score()
    assert isinstance(score, float)

def test_calculate_crossovers(sample_data):
    indicator = MovingAverageIndicator(sample_data)
    crossover_signal = indicator.calculate_crossovers()
    assert crossover_signal in [0.0, 1.0]

def test_calculate_score(sample_data):
    indicator = MovingAverageIndicator(sample_data)
    score = indicator.calculate_score()
    assert isinstance(score, float)