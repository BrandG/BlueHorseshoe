"""
Tests for the strategy registry (Phase 2).
"""

import pytest

from bluehorseshoe.analysis.strategy_interface import (
    BaselineStrategy,
    DeepDownAdxStrategy,
    DeepOversoldStrategy,
    DeepOversoldHAStrategy,
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

    def test_deep_oversold_ha(self):
        strat = get_strategy("deep_oversold_ha")
        assert isinstance(strat, DeepOversoldHAStrategy)
        assert strat.name == "deep_oversold_ha"

    def test_adx_didown(self):
        strat = get_strategy("adx_didown")
        assert isinstance(strat, DeepDownAdxStrategy)
        assert strat.name == "adx_didown"

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown strategy 'bogus'"):
            get_strategy("bogus")


class TestGetAllStrategies:

    def test_returns_five(self):
        strats = get_all_strategies()
        assert len(strats) == 5

    def test_all_are_trading_strategies(self):
        for s in get_all_strategies():
            assert isinstance(s, TradingStrategy)

    def test_order(self):
        names = [s.name for s in get_all_strategies()]
        assert names == [
            "baseline", "mean_reversion", "deep_oversold",
            "deep_oversold_ha", "adx_didown",
        ]

    def test_paper_tradeable_flags(self):
        # Only the gauntlet-validated deep-oversold sleeves are live-tradeable.
        # baseline / mean_reversion (no validated entry edge) and adx_didown
        # (modest, overlapping) are tracking-only — forward-R in the hypothesis
        # engine, no live broker slots.
        flags = {s.name: s.paper_tradeable for s in get_all_strategies()}
        live = {k for k, v in flags.items() if v}
        assert live == {"deep_oversold", "deep_oversold_ha"}
        assert flags["baseline"] is False
        assert flags["mean_reversion"] is False
        assert flags["adx_didown"] is False

    def test_edge_weights(self):
        # Cross-sleeve allocation ranks by score * edge_weight (validated per-trade R).
        # Unvalidated sleeves default to 0.0 (leftover-only); HA must out-weight bare
        # DeepOS or it would tie under ranking (it inherits DeepOS otherwise).
        w = {s.name: s.edge_weight for s in get_all_strategies()}
        assert w["baseline"] == 0.0 and w["mean_reversion"] == 0.0
        assert w["deep_oversold_ha"] > w["deep_oversold"] > 0.0
        assert w["adx_didown"] > 0.0


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

    def test_deep_oversold_ha_keys(self):
        keys = get_strategy_keys("deep_oversold_ha")
        assert keys == {
            'score_key': 'deep_os_ha_score',
            'setup_key': 'deep_os_ha_setup',
            'ml_prob_key': 'deep_os_ha_ml_prob',
            'components_key': 'deep_os_ha_components',
        }

    def test_adx_didown_keys(self):
        keys = get_strategy_keys("adx_didown")
        assert keys == {
            'score_key': 'adx_didown_score',
            'setup_key': 'adx_didown_setup',
            'ml_prob_key': 'adx_didown_ml_prob',
            'components_key': 'adx_didown_components',
        }

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            get_strategy_keys("unknown")
