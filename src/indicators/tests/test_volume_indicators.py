import pytest
import pandas as pd
from src.indicators.volume_indicators import VolumeIndicator

@pytest.fixture
def sample_data():
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

def test_score_atr_spike(sample_data):
    vi = VolumeIndicator(sample_data)
    result = vi.score_atr_spike()
    expected_result = 0.0  # Update this value based on the expected result
    assert result == expected_result, f"Expected {expected_result}, but got {result}"

def test_score_atr_band(sample_data):
    vi = VolumeIndicator(sample_data)
    result = vi._score_atr_band()
    expected_result = -1.0  # Update this value based on the expected result
    assert result == expected_result, f"Expected {expected_result}, but got {result}"

def test_calculate_avg_volume(sample_data):
    vi = VolumeIndicator(sample_data)
    result = vi._calculate_avg_volume()
    expected_result = 1.0  # Update this value based on the expected result
    assert result == expected_result, f"Expected {expected_result}, but got {result}"

def test_calculate_cmf_with_ta(sample_data):
    vi = VolumeIndicator(sample_data)
    result = vi._calculate_cmf_with_ta()
    expected_result = -1.0  # Update this value based on the expected result
    assert result == expected_result, f"Expected {expected_result}, but got {result}"

def test_score_obv_trend(sample_data):
    vi = VolumeIndicator(sample_data)
    result = vi._score_obv_trend()
    expected_result = 0.0  # Update this value based on the expected result
    assert result == expected_result, f"Expected {expected_result}, but got {result}"

def test_calculate_score(sample_data):
    vi = VolumeIndicator(sample_data)
    result = vi.calculate_score()
    expected_result = -1.0  # Update this value based on the expected result
    assert result == expected_result, f"Expected {expected_result}, but got {result}"
