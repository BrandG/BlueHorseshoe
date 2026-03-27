"""
Tests for regime-adaptive weight selection.

Covers:
- get_market_health() returns 'score' key (int 0-10)
- select_weights_for_regime() picks V3 for extremes, V2 for favorable
- Boundary tests at 2/3 and 8/9
- weights_v2_full.json has all 13 categories
- Weight restore after selection
"""

import json
import os
import pytest
from unittest.mock import patch, MagicMock

from bluehorseshoe.core.config import ConfigManager, WEIGHTS_V2_FULL_FILE, WEIGHTS_V3_FILE


@pytest.fixture
def fresh_config(tmp_path):
    """Create a fresh ConfigManager with temporary weight files."""
    # Reset singleton
    ConfigManager._instance = None

    # Create temp production weights file
    prod_weights = {"trend": {"ADX_MULTIPLIER": 1.0}, "momentum": {"RSI_MULTIPLIER": 1.0}}
    prod_path = tmp_path / "weights.json"
    prod_path.write_text(json.dumps(prod_weights))

    with patch('bluehorseshoe.core.config.WEIGHTS_FILE', str(prod_path)):
        config = ConfigManager()
        yield config

    # Cleanup singleton
    ConfigManager._instance = None


@pytest.fixture
def config_with_regime_files(tmp_path):
    """Create a ConfigManager with V2 and V3 regime weight files."""
    ConfigManager._instance = None

    prod_weights = {"trend": {"ADX_MULTIPLIER": 0.5}}
    prod_path = tmp_path / "weights.json"
    prod_path.write_text(json.dumps(prod_weights))

    v2_weights = {
        "trend": {"ADX_MULTIPLIER": 1.0, "DONCHIAN_MULTIPLIER": 1.5},
        "momentum": {"RSI_MULTIPLIER": 0.0},
    }
    v2_path = tmp_path / "weights_v2_full.json"
    v2_path.write_text(json.dumps(v2_weights))

    v3_weights = {
        "trend": {"ADX_MULTIPLIER": 0.0, "DONCHIAN_MULTIPLIER": 0.0},
        "momentum": {"RSI_MULTIPLIER": 1.0},
    }
    v3_path = tmp_path / "weights_v3.json"
    v3_path.write_text(json.dumps(v3_weights))

    with patch('bluehorseshoe.core.config.WEIGHTS_FILE', str(prod_path)), \
         patch('bluehorseshoe.core.config.WEIGHTS_V2_FULL_FILE', str(v2_path)), \
         patch('bluehorseshoe.core.config.WEIGHTS_V3_FILE', str(v3_path)):
        config = ConfigManager()
        yield config

    ConfigManager._instance = None


class TestMarketHealthScore:
    """Test that get_market_health() returns a 'score' key."""

    def test_market_health_returns_score_key(self):
        """get_market_health() return dict includes 'score' as int 0-10."""
        with patch('bluehorseshoe.analysis.market_regime.MarketRegime._get_index_health') as mock_health, \
             patch('bluehorseshoe.analysis.market_regime.MarketRegime._calculate_breadth') as mock_breadth:
            mock_health.return_value = (3, {'score': 3, 'trend': 'Uptrend'})
            mock_breadth.return_value = 0.7

            from bluehorseshoe.analysis.market_regime import MarketRegime
            result = MarketRegime.get_market_health()

            assert 'score' in result
            assert isinstance(result['score'], int)

    def test_market_health_score_range(self):
        """Score should be 0-10 depending on index scores + breadth."""
        from bluehorseshoe.analysis.market_regime import MarketRegime

        # Max score: 2 indices * 4 points + 2 breadth = 10
        with patch.object(MarketRegime, '_get_index_health', return_value=(4, {})), \
             patch.object(MarketRegime, '_calculate_breadth', return_value=0.8):
            result = MarketRegime.get_market_health()
            assert result['score'] == 10

        # Min score: 0 + 0 breadth
        with patch.object(MarketRegime, '_get_index_health', return_value=(0, {})), \
             patch.object(MarketRegime, '_calculate_breadth', return_value=0.2):
            result = MarketRegime.get_market_health()
            assert result['score'] == 0


class TestWeightSelection:
    """Test regime-adaptive weight selection logic."""

    def test_extreme_bear_selects_v3(self, config_with_regime_files):
        """Score <= 2 should select V3 weights."""
        for score in [0, 1, 2]:
            label = config_with_regime_files.select_weights_for_regime(score)
            assert label == 'v3', f"Score {score} should select v3"

    def test_favorable_selects_v2(self, config_with_regime_files):
        """Score 3-8 should select V2 weights."""
        for score in [3, 4, 5, 6, 7, 8]:
            label = config_with_regime_files.select_weights_for_regime(score)
            assert label == 'v2', f"Score {score} should select v2"

    def test_extreme_bull_selects_v3(self, config_with_regime_files):
        """Score >= 9 should select V3 weights."""
        for score in [9, 10]:
            label = config_with_regime_files.select_weights_for_regime(score)
            assert label == 'v3', f"Score {score} should select v3"

    def test_boundary_2_3(self, config_with_regime_files):
        """Boundary: score 2 -> V3, score 3 -> V2."""
        assert config_with_regime_files.select_weights_for_regime(2) == 'v3'
        assert config_with_regime_files.select_weights_for_regime(3) == 'v2'

    def test_boundary_8_9(self, config_with_regime_files):
        """Boundary: score 8 -> V2, score 9 -> V3."""
        assert config_with_regime_files.select_weights_for_regime(8) == 'v2'
        assert config_with_regime_files.select_weights_for_regime(9) == 'v3'

    def test_weights_actually_swapped(self, config_with_regime_files):
        """After selection, _weights should reflect the chosen version."""
        config_with_regime_files.select_weights_for_regime(5)  # V2
        assert config_with_regime_files.get_weights('trend')['ADX_MULTIPLIER'] == 1.0

        config_with_regime_files.select_weights_for_regime(0)  # V3
        assert config_with_regime_files.get_weights('trend')['ADX_MULTIPLIER'] == 0.0

    def test_weight_restore_after_selection(self, config_with_regime_files):
        """load_weights() should restore production weights after regime selection."""
        original = config_with_regime_files.get_weights('trend').copy()
        config_with_regime_files.select_weights_for_regime(5)  # V2
        config_with_regime_files.load_weights()  # Restore
        restored = config_with_regime_files.get_weights('trend')
        assert restored == original


class TestV2FullWeights:
    """Test that weights_v2_full.json has all required categories."""

    def test_v2_full_has_all_13_categories(self):
        """weights_v2_full.json should have all 13 weight categories."""
        v2_full_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'weights_v2_full.json'
        )
        if not os.path.exists(v2_full_path):
            pytest.skip("weights_v2_full.json not found")

        with open(v2_full_path, 'r', encoding='utf-8') as f:
            weights = json.load(f)

        expected_categories = [
            'trend', 'momentum', 'volume', 'candlestick', 'mean_reversion', 'price_action',
            'mr_trend', 'mr_momentum', 'mr_volume', 'mr_candlestick', 'mr_price_action',
            'mean_reversion_specific', 'mr_mean_reversion_specific',
        ]
        for cat in expected_categories:
            assert cat in weights, f"Missing category: {cat}"

    def test_v2_full_baseline_matches_v2(self):
        """V2-full baseline categories should match original V2 weights."""
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        v2_path = os.path.join(base_dir, 'weights_v2.json')
        v2_full_path = os.path.join(base_dir, 'weights_v2_full.json')

        if not os.path.exists(v2_path):
            pytest.skip("weights_v2.json not found")

        with open(v2_path, 'r', encoding='utf-8') as f:
            v2 = json.load(f)
        with open(v2_full_path, 'r', encoding='utf-8') as f:
            v2_full = json.load(f)

        for cat in v2:
            assert v2_full[cat] == v2[cat], f"Category {cat} differs between V2 and V2-full"


class TestAdaptiveBacktest:
    """Test the adaptive version selection helper for backtest runner."""

    def test_select_adaptive_version(self):
        """Verify select_adaptive_version matches the regime rule."""
        # Import inline to avoid path issues in unit tests
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "run_clean_backtest",
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "run_clean_backtest.py")
        )
        if spec is None:
            pytest.skip("run_clean_backtest.py not found")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        assert mod.select_adaptive_version(0) == "v3"
        assert mod.select_adaptive_version(2) == "v3"
        assert mod.select_adaptive_version(3) == "v2"
        assert mod.select_adaptive_version(5) == "v2"
        assert mod.select_adaptive_version(8) == "v2"
        assert mod.select_adaptive_version(9) == "v3"
        assert mod.select_adaptive_version(10) == "v3"
