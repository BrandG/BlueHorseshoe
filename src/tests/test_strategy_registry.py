"""
Tests for the strategy registry (Phase 2).
"""

import pytest

from bluehorseshoe.analysis.strategy_interface import (
    BaselineStrategy,
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

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown strategy 'bogus'"):
            get_strategy("bogus")


class TestGetAllStrategies:

    def test_returns_two(self):
        strats = get_all_strategies()
        assert len(strats) == 2

    def test_all_are_trading_strategies(self):
        for s in get_all_strategies():
            assert isinstance(s, TradingStrategy)

    def test_order(self):
        names = [s.name for s in get_all_strategies()]
        assert names == ["baseline", "mean_reversion"]


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

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            get_strategy_keys("unknown")
