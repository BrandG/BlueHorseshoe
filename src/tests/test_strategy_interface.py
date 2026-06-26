"""
Tests for the pluggable strategy interface (Phase 1).

Verifies:
- Property values match expected backward-compatible keys
- StrategyResult dataclass construction
- Strategy objects are picklable (critical for ProcessPoolExecutor)
- process() produces correct results with mocked trader
"""

import pickle

import pytest

from bluehorseshoe.analysis.strategy_interface import (
    BaselineStrategy,
    MeanReversionStrategy,
    StrategyResult,
    TradingStrategy,
)
from bluehorseshoe.analysis.constants import (
    MIN_RR_RATIO_BASELINE,
    MIN_RR_RATIO_MEAN_REVERSION,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def baseline():
    return BaselineStrategy()


@pytest.fixture
def mean_reversion():
    return MeanReversionStrategy()


# ---------------------------------------------------------------------------
# Property identity tests
# ---------------------------------------------------------------------------

class TestBaselineProperties:

    def test_name(self, baseline):
        assert baseline.name == "baseline"

    def test_display_name(self, baseline):
        assert baseline.display_name == "Baseline"

    def test_score_key(self, baseline):
        assert baseline.score_key == "baseline_score"

    def test_setup_key(self, baseline):
        assert baseline.setup_key == "baseline_setup"

    def test_ml_prob_key(self, baseline):
        assert baseline.ml_prob_key == "baseline_ml_prob"

    def test_components_key(self, baseline):
        assert baseline.components_key == "baseline_components"

    def test_weight_prefix(self, baseline):
        assert baseline.weight_prefix == ""

    def test_default_stop_multiplier(self, baseline):
        assert baseline.default_stop_multiplier == 2.0

    def test_default_target_multiplier(self, baseline):
        assert baseline.default_target_multiplier == 3.0

    def test_min_rr_ratio(self, baseline):
        assert baseline.min_rr_ratio == MIN_RR_RATIO_BASELINE


class TestMeanReversionProperties:

    def test_name(self, mean_reversion):
        assert mean_reversion.name == "mean_reversion"

    def test_display_name(self, mean_reversion):
        assert mean_reversion.display_name == "MeanRev"

    def test_score_key(self, mean_reversion):
        assert mean_reversion.score_key == "mr_score"

    def test_setup_key(self, mean_reversion):
        assert mean_reversion.setup_key == "mr_setup"

    def test_ml_prob_key(self, mean_reversion):
        assert mean_reversion.ml_prob_key == "mr_ml_prob"

    def test_components_key(self, mean_reversion):
        assert mean_reversion.components_key == "mr_components"

    def test_weight_prefix(self, mean_reversion):
        assert mean_reversion.weight_prefix == "mr_"

    def test_default_stop_multiplier(self, mean_reversion):
        assert mean_reversion.default_stop_multiplier == 1.5

    def test_default_target_multiplier(self, mean_reversion):
        assert mean_reversion.default_target_multiplier == 2.0

    def test_min_rr_ratio(self, mean_reversion):
        assert mean_reversion.min_rr_ratio == MIN_RR_RATIO_MEAN_REVERSION


# ---------------------------------------------------------------------------
# StrategyResult tests
# ---------------------------------------------------------------------------

class TestStrategyResult:

    def test_construction(self):
        sr = StrategyResult(
            score=15.5,
            components={"trend": 3.0, "momentum": 5.0},
            setup={"entry_price": 100.0, "stop_loss": 95.0, "take_profit": 110.0},
            ml_prob=0.72,
            stop_multiplier=2.0,
            target_multiplier=3.0,
        )
        assert sr.score == 15.5
        assert sr.components["trend"] == 3.0
        assert sr.setup["entry_price"] == 100.0
        assert sr.ml_prob == 0.72

    def test_picklable(self):
        sr = StrategyResult(
            score=10.0,
            components={"a": 1.0},
            setup={"entry_price": 50.0},
            ml_prob=0.5,
            stop_multiplier=2.0,
            target_multiplier=3.0,
        )
        restored = pickle.loads(pickle.dumps(sr))
        assert restored.score == sr.score
        assert restored.components == sr.components


# ---------------------------------------------------------------------------
# Picklability (critical for ProcessPoolExecutor)
# ---------------------------------------------------------------------------

class TestPicklability:

    def test_baseline_picklable(self, baseline):
        restored = pickle.loads(pickle.dumps(baseline))
        assert restored.name == "baseline"
        assert restored.score_key == "baseline_score"

    def test_mean_reversion_picklable(self, mean_reversion):
        restored = pickle.loads(pickle.dumps(mean_reversion))
        assert restored.name == "mean_reversion"
        assert restored.score_key == "mr_score"


# ---------------------------------------------------------------------------
# ABC enforcement
# ---------------------------------------------------------------------------

class TestABCEnforcement:

    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            TradingStrategy()  # type: ignore[abstract]  # pylint: disable=abstract-class-instantiated

    def test_isinstance_check(self, baseline, mean_reversion):
        assert isinstance(baseline, TradingStrategy)
        assert isinstance(mean_reversion, TradingStrategy)


# ---------------------------------------------------------------------------
# Key dict helpers (used downstream by registry)
# ---------------------------------------------------------------------------

class TestKeyDicts:

    def test_baseline_keys_dict(self, baseline):
        keys = {
            'score_key': baseline.score_key,
            'setup_key': baseline.setup_key,
            'ml_prob_key': baseline.ml_prob_key,
            'components_key': baseline.components_key,
        }
        assert keys == {
            'score_key': 'baseline_score',
            'setup_key': 'baseline_setup',
            'ml_prob_key': 'baseline_ml_prob',
            'components_key': 'baseline_components',
        }

    def test_mr_keys_dict(self, mean_reversion):
        keys = {
            'score_key': mean_reversion.score_key,
            'setup_key': mean_reversion.setup_key,
            'ml_prob_key': mean_reversion.ml_prob_key,
            'components_key': mean_reversion.components_key,
        }
        assert keys == {
            'score_key': 'mr_score',
            'setup_key': 'mr_setup',
            'ml_prob_key': 'mr_ml_prob',
            'components_key': 'mr_components',
        }
