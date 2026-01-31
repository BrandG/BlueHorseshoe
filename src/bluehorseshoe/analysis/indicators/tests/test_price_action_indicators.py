"""
Unit tests for Price Action Indicators (Gap Analysis).
"""

import unittest
import pandas as pd
import numpy as np
from bluehorseshoe.analysis.indicators.price_action_indicators import PriceActionIndicator


class TestPriceActionIndicator(unittest.TestCase):
    """Test cases for PriceActionIndicator class."""

    def setUp(self):
        """Set up test data."""
        self.dates = pd.date_range('2025-01-01', periods=25)

    def test_strong_gap_up_high_volume(self):
        """Test strong gap up (>2%) with high volume (>1.5x)."""
        data = pd.DataFrame({
            'date': self.dates,
            'open': [100.0] * 24 + [105.0],  # 5% gap up on last day
            'close': [100.0] * 25,
            'high': [101.0] * 25,
            'low': [99.0] * 25,
            'volume': [1000000] * 24 + [2000000]  # 2x volume on gap day
        })

        indicator = PriceActionIndicator(data)
        score = indicator.calculate_gap_score()

        # Should return +2.0 for strong gap with strong volume
        self.assertEqual(score, 2.0)

    def test_moderate_gap_up_moderate_volume(self):
        """Test moderate gap up (>1%) with moderate volume (>1.2x)."""
        data = pd.DataFrame({
            'date': self.dates,
            'open': [100.0] * 24 + [101.5],  # 1.5% gap up
            'close': [100.0] * 25,
            'high': [101.0] * 25,
            'low': [99.0] * 25,
            'volume': [1000000] * 24 + [1300000]  # 1.3x volume
        })

        indicator = PriceActionIndicator(data)
        score = indicator.calculate_gap_score()

        # Should return +1.0 for moderate gap with good volume
        self.assertEqual(score, 1.0)

    def test_gap_up_weak_volume(self):
        """Test gap up with weak volume (no confirmation)."""
        data = pd.DataFrame({
            'date': self.dates,
            'open': [100.0] * 24 + [102.5],  # 2.5% gap up
            'close': [100.0] * 25,
            'high': [101.0] * 25,
            'low': [99.0] * 25,
            'volume': [1000000] * 24 + [900000]  # Below average volume
        })

        indicator = PriceActionIndicator(data)
        score = indicator.calculate_gap_score()

        # Should return +1.0 for strong gap but weak volume
        self.assertEqual(score, 1.0)

    def test_strong_gap_down(self):
        """Test strong gap down (>2%)."""
        data = pd.DataFrame({
            'date': self.dates,
            'open': [100.0] * 24 + [97.0],  # 3% gap down
            'close': [100.0] * 25,
            'high': [101.0] * 25,
            'low': [99.0] * 25,
            'volume': [1000000] * 25
        })

        indicator = PriceActionIndicator(data)
        score = indicator.calculate_gap_score()

        # Should return -2.0 for strong gap down
        self.assertEqual(score, -2.0)

    def test_moderate_gap_down(self):
        """Test moderate gap down (>1%)."""
        data = pd.DataFrame({
            'date': self.dates,
            'open': [100.0] * 24 + [98.5],  # 1.5% gap down
            'close': [100.0] * 25,
            'high': [101.0] * 25,
            'low': [99.0] * 25,
            'volume': [1000000] * 25
        })

        indicator = PriceActionIndicator(data)
        score = indicator.calculate_gap_score()

        # Should return -1.0 for moderate gap down
        self.assertEqual(score, -1.0)

    def test_no_significant_gap(self):
        """Test no significant gap."""
        data = pd.DataFrame({
            'date': self.dates,
            'open': [100.0] * 25,  # No gap
            'close': [100.0] * 25,
            'high': [101.0] * 25,
            'low': [99.0] * 25,
            'volume': [1000000] * 25
        })

        indicator = PriceActionIndicator(data)
        score = indicator.calculate_gap_score()

        # Should return 0.0 for no gap
        self.assertEqual(score, 0.0)

    def test_insufficient_data(self):
        """Test with insufficient data (less than 21 days)."""
        data = pd.DataFrame({
            'date': pd.date_range('2025-01-01', periods=15),
            'open': [100.0] * 15,
            'close': [100.0] * 15,
            'high': [101.0] * 15,
            'low': [99.0] * 15,
            'volume': [1000000] * 15
        })

        indicator = PriceActionIndicator(data)
        score = indicator.calculate_gap_score()

        # Should return 0.0 when insufficient data
        self.assertEqual(score, 0.0)

    def test_get_score_integration(self):
        """Test that get_score properly integrates gap calculation."""
        data = pd.DataFrame({
            'date': self.dates,
            'open': [100.0] * 24 + [103.0],  # 3% gap up
            'close': [100.0] * 25,
            'high': [101.0] * 25,
            'low': [99.0] * 25,
            'volume': [1000000] * 24 + [1800000]  # 1.8x volume
        })

        # Note: GAP_MULTIPLIER in weights.json affects this
        indicator = PriceActionIndicator(data)
        result = indicator.get_score()

        # Check that result is an IndicatorScore namedtuple
        self.assertTrue(hasattr(result, 'buy'))
        self.assertTrue(hasattr(result, 'sell'))

        # Sell score should always be 0.0 for price action
        self.assertEqual(result.sell, 0.0)


if __name__ == '__main__':
    unittest.main()
