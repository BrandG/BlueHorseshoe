"""
Unit tests for VWAP (Volume Weighted Average Price) indicator.
"""

import unittest
import pandas as pd
import numpy as np
from bluehorseshoe.analysis.indicators.volume_indicators import VolumeIndicator


class TestVWAPIndicator(unittest.TestCase):
    """Test cases for VWAP calculation in VolumeIndicator."""

    def setUp(self):
        """Set up test data."""
        self.dates = pd.date_range('2025-01-01', periods=30)
        self.base_volume = 1000000

    def test_price_strongly_above_vwap(self):
        """Test when price is >2% above VWAP (strong institutional support)."""
        # Create uptrending data where current price >> VWAP
        data = pd.DataFrame({
            'date': self.dates,
            'high': np.linspace(95, 105, 30),
            'low': np.linspace(93, 103, 30),
            'close': np.linspace(94, 104, 30),  # Strong uptrend
            'volume': np.ones(30) * self.base_volume
        })

        indicator = VolumeIndicator(data)
        score = indicator.calculate_vwap(window=20)

        # Price should be >2% above VWAP
        self.assertEqual(score, 2.0)

    def test_price_moderately_above_vwap(self):
        """Test when price is 1-2% above VWAP."""
        # Create data with price slightly above VWAP
        data = pd.DataFrame({
            'date': self.dates,
            'high': np.linspace(98, 101.5, 30),
            'low': np.linspace(96, 99.5, 30),
            'close': np.linspace(97, 100.5, 30),  # Mild uptrend
            'volume': np.ones(30) * self.base_volume
        })

        indicator = VolumeIndicator(data)
        score = indicator.calculate_vwap(window=20)

        # Price should be 1-2% above VWAP
        self.assertEqual(score, 1.0)

    def test_price_near_vwap(self):
        """Test when price is within ±1% of VWAP (neutral)."""
        # Create flat data where price = VWAP
        data = pd.DataFrame({
            'date': self.dates,
            'high': np.ones(30) * 101,
            'low': np.ones(30) * 99,
            'close': np.ones(30) * 100,  # Flat at 100
            'volume': np.ones(30) * self.base_volume
        })

        indicator = VolumeIndicator(data)
        score = indicator.calculate_vwap(window=20)

        # Price should be near VWAP (within ±1%)
        self.assertEqual(score, 0.0)

    def test_price_moderately_below_vwap(self):
        """Test when price is 1-2% below VWAP."""
        # Create data with price below VWAP
        data = pd.DataFrame({
            'date': self.dates,
            'high': np.linspace(104, 98, 30),
            'low': np.linspace(102, 96, 30),
            'close': np.linspace(103, 97, 30),  # Downtrend to get price 1-2% below VWAP
            'volume': np.ones(30) * self.base_volume
        })

        indicator = VolumeIndicator(data)
        score = indicator.calculate_vwap(window=20)

        # Price should be 1-2% below VWAP
        self.assertEqual(score, -1.0)

    def test_price_strongly_below_vwap(self):
        """Test when price is >2% below VWAP (weak institutional support)."""
        # Create downtrending data where current price << VWAP
        data = pd.DataFrame({
            'date': self.dates,
            'high': np.linspace(105, 95, 30),
            'low': np.linspace(103, 93, 30),
            'close': np.linspace(104, 94, 30),  # Strong downtrend
            'volume': np.ones(30) * self.base_volume
        })

        indicator = VolumeIndicator(data)
        score = indicator.calculate_vwap(window=20)

        # Price should be >2% below VWAP
        self.assertEqual(score, -2.0)

    def test_insufficient_data(self):
        """Test with insufficient data (less than window size)."""
        data = pd.DataFrame({
            'date': pd.date_range('2025-01-01', periods=15),
            'high': np.ones(15) * 101,
            'low': np.ones(15) * 99,
            'close': np.ones(15) * 100,
            'volume': np.ones(15) * self.base_volume
        })

        indicator = VolumeIndicator(data)
        score = indicator.calculate_vwap(window=20)

        # Should return 0.0 when insufficient data
        self.assertEqual(score, 0.0)

    def test_vwap_with_varying_volume(self):
        """Test VWAP calculation with varying volume (volume-weighted)."""
        # Create data where high volume days are at lower prices
        # This should pull VWAP down
        volumes = [500000] * 15 + [2000000] * 5 + [500000] * 10  # High volume in middle
        closes = [95] * 15 + [90] * 5 + [100] * 10  # Low prices during high volume

        data = pd.DataFrame({
            'date': self.dates,
            'high': [c + 1 for c in closes],
            'low': [c - 1 for c in closes],
            'close': closes,
            'volume': volumes
        })

        indicator = VolumeIndicator(data)
        score = indicator.calculate_vwap(window=20)

        # Current price (100) should be well above VWAP (pulled down by high volume at 90)
        # So we expect a positive score
        self.assertGreater(score, 0)

    def test_get_score_integration(self):
        """Test that VWAP integrates properly with get_score method."""
        data = pd.DataFrame({
            'date': self.dates,
            'high': np.linspace(95, 105, 30),
            'low': np.linspace(93, 103, 30),
            'close': np.linspace(94, 104, 30),
            'volume': np.ones(30) * self.base_volume
        })

        indicator = VolumeIndicator(data)

        # Test with VWAP explicitly enabled
        result = indicator.get_score(enabled_sub_indicators=['vwap'])

        # Check that result is an IndicatorScore namedtuple
        self.assertTrue(hasattr(result, 'buy'))
        self.assertTrue(hasattr(result, 'sell'))

        # Sell score should always be 0.0 for volume indicators
        self.assertEqual(result.sell, 0.0)

        # Buy score should be non-zero if VWAP is enabled (but may be 0 if VWAP_MULTIPLIER=0)


if __name__ == '__main__':
    unittest.main()
