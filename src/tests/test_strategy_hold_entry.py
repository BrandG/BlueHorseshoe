from bluehorseshoe.analysis.strategy_interface import (
    BaselineStrategy,
    DeepOversoldStrategy,
    DeepOversoldHAStrategy,
    MeanReversionStrategy,
)


def test_baseline_hold_days_follow_regime_profiles():
    strategy = BaselineStrategy()

    assert strategy.get_hold_days("Neutral") == 5
    assert strategy.get_hold_days("Bullish") == 5
    assert strategy.get_hold_days("Bearish") == 7
    assert strategy.get_hold_days() == 5
    assert strategy.get_hold_days(None) == 5


def test_mean_reversion_hold_days_follow_regime_profiles():
    strategy = MeanReversionStrategy()

    assert strategy.get_hold_days("Neutral") == 5
    assert strategy.get_hold_days("Bullish") == 5
    assert strategy.get_hold_days("Bearish") == 7
    assert strategy.get_hold_days() == 5
    assert strategy.get_hold_days(None) == 5


def test_deep_oversold_hold_days_are_regime_invariant():
    strategy = DeepOversoldStrategy()

    for regime in (None, "Neutral", "Bullish", "Bearish"):
        assert strategy.get_hold_days(regime) == 10


def test_deep_oversold_ha_inherits_deep_hold_and_entry():
    # The HA sleeve must evaluate with the same faithful horizon/fill as DeepOS.
    strategy = DeepOversoldHAStrategy()
    for regime in (None, "Neutral", "Bullish", "Bearish"):
        assert strategy.get_hold_days(regime) == 10
    assert strategy.entry_style == "marketable_next_open"


def test_strategy_entry_styles():
    assert BaselineStrategy().entry_style == "limit_below"
    assert MeanReversionStrategy().entry_style == "limit_below"
    assert DeepOversoldStrategy().entry_style == "marketable_next_open"
    assert DeepOversoldHAStrategy().entry_style == "marketable_next_open"
