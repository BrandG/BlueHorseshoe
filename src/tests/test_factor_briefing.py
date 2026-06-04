"""Tests for the locked factor groups and the factor-briefing renderer."""
from bluehorseshoe.analysis.factor_groups import (
    AVOID, UNTESTED, VALIDATED, get_factor_groups, get_group, group_for_strategy,
)
from bluehorseshoe.reporting.factor_briefing import render_factor_briefing


def _deepos(sym, score, age, rsi=22.0, dvol=80.0):
    return {"symbol": sym, "strategy": "DeepOS", "score": score, "close": 100.0,
            "stop_loss": 96.0, "target": 108.0,
            "reasons": [f"oversold_age={age:.1f}", f"rsi={rsi:.1f}", f"dollar_vol_M={dvol:.1f}"]}


class TestFactorGroups:
    def test_dislocation_is_the_validated_green_group(self):
        g = get_group("dislocation")
        assert g.status == VALIDATED
        assert g.ranking_dimension == "oversold_age"
        assert g.strategy == "deep_oversold"

    def test_strategy_maps_to_group(self):
        assert group_for_strategy("deep_oversold").key == "dislocation"
        assert group_for_strategy("baseline") is None

    def test_no_standalone_trend_factor(self):
        # trend-direction signals are absorbed into dislocation (the no-edge core);
        # there is deliberately no "trend" group.
        assert not any(g.key == "trend" for g in get_factor_groups())
        disloc = get_group("dislocation")
        assert {"psar_dist", "di_spread", "sma_cross"} <= set(disloc.members)

    def test_adx_lives_with_volatility(self):
        assert "adx" in get_group("volatility").members

    def test_only_dislocation_validated_today(self):
        validated = [g.key for g in get_factor_groups() if g.status == VALIDATED]
        assert validated == ["dislocation"]


class TestBriefingRenderer:
    def test_dislocation_populated_and_depth_ranked(self):
        cands = [_deepos("AAA", 25.0, 10), _deepos("BBB", 14.5, 3)]
        out = render_factor_briefing(cands, target_date="2026-06-03")
        assert "AAA" in out and "BBB" in out
        # deepest (AAA, age 10, score 25) ranks above BBB
        assert out.index("AAA") < out.index("BBB")
        assert "✓ VALIDATED" in out and "●" in out

    def test_avoid_and_untested_columns_show_no_buys(self):
        out = render_factor_briefing([_deepos("AAA", 25.0, 10)])
        assert "✗ AVOID" in out and "— UNTESTED" in out
        # the Volatility (AVOID) column must not be presented as a buy list
        assert "not a buy" in out

    def test_other_strategy_does_not_leak_into_dislocation(self):
        baseline_cand = {"symbol": "ZZZ", "strategy": "Baseline", "score": 30.0,
                         "close": 50.0, "stop_loss": 48.0, "target": 55.0, "reasons": []}
        out = render_factor_briefing([baseline_cand])
        # ZZZ is not a DeepOS candidate → must not appear in the dislocation column
        assert "ZZZ" not in out

    def test_all_locked_groups_render_as_columns(self):
        out = render_factor_briefing([])
        for g in get_factor_groups():
            assert g.label in out
