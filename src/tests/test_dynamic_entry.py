"""Tests for dynamic entry strategy."""
import pytest
import pandas as pd
from bluehorseshoe.analysis.strategy import SwingTrader
from bluehorseshoe.analysis.constants import (
    SIGNAL_STRENGTH_THRESHOLDS,
    ENTRY_DISCOUNT_BY_SIGNAL
)


class TestSignalStrengthClassification:
    """Test signal strength tier classification."""

    def test_extreme_signal(self):
        """Test EXTREME signal classification (80+)."""
        assert SwingTrader._classify_signal_strength(85) == 'EXTREME'
        assert SwingTrader._classify_signal_strength(80) == 'EXTREME'
        assert SwingTrader._classify_signal_strength(100) == 'EXTREME'

    def test_high_signal(self):
        """Test HIGH signal classification (60-79)."""
        assert SwingTrader._classify_signal_strength(65) == 'HIGH'
        assert SwingTrader._classify_signal_strength(60) == 'HIGH'
        assert SwingTrader._classify_signal_strength(79) == 'HIGH'

    def test_medium_signal(self):
        """Test MEDIUM signal classification (40-59)."""
        assert SwingTrader._classify_signal_strength(45) == 'MEDIUM'
        assert SwingTrader._classify_signal_strength(40) == 'MEDIUM'
        assert SwingTrader._classify_signal_strength(59) == 'MEDIUM'

    def test_low_signal(self):
        """Test LOW signal classification (20-39)."""
        assert SwingTrader._classify_signal_strength(25) == 'LOW'
        assert SwingTrader._classify_signal_strength(20) == 'LOW'
        assert SwingTrader._classify_signal_strength(39) == 'LOW'

    def test_weak_signal(self):
        """Test WEAK signal classification (<20)."""
        assert SwingTrader._classify_signal_strength(15) == 'WEAK'
        assert SwingTrader._classify_signal_strength(0) == 'WEAK'
        assert SwingTrader._classify_signal_strength(19) == 'WEAK'

    def test_boundary_values(self):
        """Test exact threshold boundaries."""
        assert SwingTrader._classify_signal_strength(80) == 'EXTREME'
        assert SwingTrader._classify_signal_strength(79.99) == 'HIGH'
        assert SwingTrader._classify_signal_strength(60) == 'HIGH'
        assert SwingTrader._classify_signal_strength(59.99) == 'MEDIUM'
        assert SwingTrader._classify_signal_strength(40) == 'MEDIUM'
        assert SwingTrader._classify_signal_strength(39.99) == 'LOW'
        assert SwingTrader._classify_signal_strength(20) == 'LOW'
        assert SwingTrader._classify_signal_strength(19.99) == 'WEAK'


class TestDynamicDiscountCalculation:
    """Test dynamic ATR discount calculation."""

    def test_extreme_discount(self):
        """Test EXTREME signal gets 0.05 discount."""
        assert SwingTrader._get_dynamic_atr_discount(85) == 0.05
        assert SwingTrader._get_dynamic_atr_discount(100) == 0.05

    def test_high_discount(self):
        """Test HIGH signal gets 0.10 discount."""
        assert SwingTrader._get_dynamic_atr_discount(65) == 0.10
        assert SwingTrader._get_dynamic_atr_discount(75) == 0.10

    def test_medium_discount(self):
        """Test MEDIUM signal gets 0.20 discount (default)."""
        assert SwingTrader._get_dynamic_atr_discount(45) == 0.20
        assert SwingTrader._get_dynamic_atr_discount(50) == 0.20

    def test_low_discount(self):
        """Test LOW signal gets 0.35 discount."""
        assert SwingTrader._get_dynamic_atr_discount(25) == 0.35
        assert SwingTrader._get_dynamic_atr_discount(30) == 0.35

    def test_weak_discount(self):
        """Test WEAK signal gets 0.50 discount."""
        assert SwingTrader._get_dynamic_atr_discount(15) == 0.50
        assert SwingTrader._get_dynamic_atr_discount(5) == 0.50

    def test_zero_score(self):
        """Test zero score defaults to WEAK."""
        assert SwingTrader._get_dynamic_atr_discount(0) == 0.50


class TestEntryPriceCalculation:
    """Test entry price calculation with dynamic discount."""

    @pytest.fixture
    def trader(self):
        """Create SwingTrader instance."""
        return SwingTrader()

    @pytest.fixture
    def mock_data(self):
        """Create mock price data."""
        last_row = pd.Series({
            'close': 100.0,
            'high': 101.0,
            'low': 99.0,
            'volume': 1000000
        })
        ema9 = 98.0
        atr = 2.0
        return last_row, ema9, atr

    def test_extreme_signal_entry(self, trader, mock_data):
        """Test EXTREME signal (0.05 discount) entry calculation."""
        last_row, ema9, atr = mock_data
        entry, discount, strength = trader._determine_baseline_entry(
            last_row, ema9, atr, technical_score=85
        )

        assert entry == pytest.approx(100.0 - (0.05 * 2.0))  # 99.90
        assert discount == 0.05
        assert strength == 'EXTREME'

    def test_high_signal_entry(self, trader, mock_data):
        """Test HIGH signal (0.10 discount) entry calculation."""
        last_row, ema9, atr = mock_data
        entry, discount, strength = trader._determine_baseline_entry(
            last_row, ema9, atr, technical_score=65
        )

        assert entry == pytest.approx(100.0 - (0.10 * 2.0))  # 99.80
        assert discount == 0.10
        assert strength == 'HIGH'

    def test_medium_signal_entry(self, trader, mock_data):
        """Test MEDIUM signal (0.20 discount - current default) entry calculation."""
        last_row, ema9, atr = mock_data
        entry, discount, strength = trader._determine_baseline_entry(
            last_row, ema9, atr, technical_score=45
        )

        assert entry == pytest.approx(100.0 - (0.20 * 2.0))  # 99.60
        assert discount == 0.20
        assert strength == 'MEDIUM'

    def test_low_signal_entry(self, trader, mock_data):
        """Test LOW signal (0.35 discount) entry calculation."""
        last_row, ema9, atr = mock_data
        entry, discount, strength = trader._determine_baseline_entry(
            last_row, ema9, atr, technical_score=25
        )

        assert entry == pytest.approx(100.0 - (0.35 * 2.0))  # 99.30
        assert discount == 0.35
        assert strength == 'LOW'

    def test_weak_signal_entry(self, trader, mock_data):
        """Test WEAK signal (0.50 discount) entry calculation."""
        last_row, ema9, atr = mock_data
        entry, discount, strength = trader._determine_baseline_entry(
            last_row, ema9, atr, technical_score=15
        )

        assert entry == pytest.approx(100.0 - (0.50 * 2.0))  # 99.00
        assert discount == 0.50
        assert strength == 'WEAK'

    def test_default_score_backward_compat(self, trader, mock_data):
        """Test backward compatibility with default score=0."""
        last_row, ema9, atr = mock_data
        entry, discount, strength = trader._determine_baseline_entry(
            last_row, ema9, atr, technical_score=0.0
        )

        # Score 0 should give WEAK classification
        assert discount == 0.50
        assert strength == 'WEAK'

    def test_different_atr_values(self, trader):
        """Test entry calculation with different ATR values."""
        last_row = pd.Series({'close': 50.0, 'high': 51.0, 'low': 49.0, 'volume': 500000})
        ema9 = 48.0

        # Test with ATR = 1.0
        entry, discount, strength = trader._determine_baseline_entry(
            last_row, ema9, atr=1.0, technical_score=80
        )
        assert entry == pytest.approx(50.0 - (0.05 * 1.0))  # 49.95

        # Test with ATR = 5.0
        entry, discount, strength = trader._determine_baseline_entry(
            last_row, ema9, atr=5.0, technical_score=80
        )
        assert entry == pytest.approx(50.0 - (0.05 * 5.0))  # 49.75


class TestConfigurationValues:
    """Test that configuration constants are correct."""

    def test_threshold_values(self):
        """Verify signal strength thresholds."""
        assert SIGNAL_STRENGTH_THRESHOLDS['EXTREME'] == 80
        assert SIGNAL_STRENGTH_THRESHOLDS['HIGH'] == 60
        assert SIGNAL_STRENGTH_THRESHOLDS['MEDIUM'] == 40
        assert SIGNAL_STRENGTH_THRESHOLDS['LOW'] == 20

    def test_discount_values(self):
        """Verify entry discount values."""
        assert ENTRY_DISCOUNT_BY_SIGNAL['EXTREME'] == 0.05
        assert ENTRY_DISCOUNT_BY_SIGNAL['HIGH'] == 0.10
        assert ENTRY_DISCOUNT_BY_SIGNAL['MEDIUM'] == 0.20  # Current default
        assert ENTRY_DISCOUNT_BY_SIGNAL['LOW'] == 0.35
        assert ENTRY_DISCOUNT_BY_SIGNAL['WEAK'] == 0.50

    def test_discount_ordering(self):
        """Verify discounts are properly ordered (stronger signals = smaller discount)."""
        discounts = [
            ENTRY_DISCOUNT_BY_SIGNAL['EXTREME'],
            ENTRY_DISCOUNT_BY_SIGNAL['HIGH'],
            ENTRY_DISCOUNT_BY_SIGNAL['MEDIUM'],
            ENTRY_DISCOUNT_BY_SIGNAL['LOW'],
            ENTRY_DISCOUNT_BY_SIGNAL['WEAK']
        ]
        # Verify list is in ascending order
        assert discounts == sorted(discounts)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
