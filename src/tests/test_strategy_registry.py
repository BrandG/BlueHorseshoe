"""
Tests for the strategy registry (Phase 2).
"""

import pytest

from bluehorseshoe.analysis.strategy_interface import (
    BaselineStrategy,
    DeepOversoldStrategy,
    MeanReversionStrategy,
    TradingStrategy,
)
from bluehorseshoe.analysis.strategy_registry import (
    get_all_strategies,
    get_strategy,
    get_strategy_keys,
)


class TestGetStrategy:

    def test_baseline(self):
        strat = get_strategy("baseline")
        assert isinstance(strat, BaselineStrategy)
        assert strat.name == "baseline"

    def test_mean_reversion(self):
        strat = get_strategy("mean_reversion")
        assert isinstance(strat, MeanReversionStrategy)
        assert strat.name == "mean_reversion"

    def test_deep_oversold(self):
        strat = get_strategy("deep_oversold")
        assert isinstance(strat, DeepOversoldStrategy)
        assert strat.name == "deep_oversold"

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown strategy 'bogus'"):
            get_strategy("bogus")


class TestGetAllStrategies:

    def test_returns_three(self):
        strats = get_all_strategies()
        assert len(strats) == 3

    def test_all_are_trading_strategies(self):
        for s in get_all_strategies():
            assert isinstance(s, TradingStrategy)

    def test_order(self):
        names = [s.name for s in get_all_strategies()]
        assert names == ["baseline", "mean_reversion", "deep_oversold"]


class TestGetStrategyKeys:

    def test_baseline_keys(self):
        keys = get_strategy_keys("baseline")
        assert keys == {
            'score_key': 'baseline_score',
            'setup_key': 'baseline_setup',
            'ml_prob_key': 'baseline_ml_prob',
            'components_key': 'baseline_components',
        }

    def test_mr_keys(self):
        keys = get_strategy_keys("mean_reversion")
        assert keys == {
            'score_key': 'mr_score',
            'setup_key': 'mr_setup',
            'ml_prob_key': 'mr_ml_prob',
            'components_key': 'mr_components',
        }

    def test_deep_oversold_keys(self):
        keys = get_strategy_keys("deep_oversold")
        assert keys == {
            'score_key': 'deep_os_score',
            'setup_key': 'deep_os_setup',
            'ml_prob_key': 'deep_os_ml_prob',
            'components_key': 'deep_os_components',
        }

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            get_strategy_keys("unknown")
