"""Tests for bh_ftmo.analysis.strategy (BaselineStrategy)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from bh_ftmo.analysis import BaselineStrategy, Signal, load_weights
from bh_ftmo.analysis.strategy import DEFAULT_WEIGHTS_PATH


# ---- helpers -----------------------------------------------------------


def _uptrend_pair_df(n: int = 200, start_price: float = 1.1000) -> pd.DataFrame:
    """Build a synthetic BA-format DataFrame representing a steady uptrend.

    Spread is held at zero (bid == ask) so mid-price equals close; this makes
    it easy to reason about rule-firing from the generated close series.
    """
    base_ts = datetime(2025, 1, 6, 0, 0, 0)  # Monday 00:00 UTC
    rows = []
    closes = np.linspace(start_price, start_price * 1.05, n)
    highs = closes * 1.0005
    lows = closes * 0.9995
    opens = np.concatenate([[closes[0]], closes[:-1]])
    for i in range(n):
        rows.append(
            {
                "timestamp": base_ts + timedelta(hours=4 * i),
                "open_bid": opens[i], "open_ask": opens[i],
                "high_bid": highs[i], "high_ask": highs[i],
                "low_bid": lows[i], "low_ask": lows[i],
                "close_bid": closes[i], "close_ask": closes[i],
            }
        )
    return pd.DataFrame(rows)


def _downtrend_pair_df(n: int = 200, start_price: float = 1.2000) -> pd.DataFrame:
    base_ts = datetime(2025, 1, 6, 0, 0, 0)
    rows = []
    closes = np.linspace(start_price, start_price * 0.95, n)
    highs = closes * 1.0005
    lows = closes * 0.9995
    opens = np.concatenate([[closes[0]], closes[:-1]])
    for i in range(n):
        rows.append(
            {
                "timestamp": base_ts + timedelta(hours=4 * i),
                "open_bid": opens[i], "open_ask": opens[i],
                "high_bid": highs[i], "high_ask": highs[i],
                "low_bid": lows[i], "low_ask": lows[i],
                "close_bid": closes[i], "close_ask": closes[i],
            }
        )
    return pd.DataFrame(rows)


# ---- Signal dataclass --------------------------------------------------


def test_signal_is_frozen():
    sig = Signal(
        symbol="EUR_USD",
        strategy="baseline",
        timestamp=datetime(2025, 1, 1),
        direction=1,
        score=4.5,
        components={"trend_above_ema_50": 1.0},
        above_threshold=True,
    )
    with pytest.raises(Exception):
        sig.score = 99.0  # type: ignore[misc]


def test_signal_defaults():
    sig = Signal(
        symbol="EUR_USD",
        strategy="baseline",
        timestamp=datetime(2025, 1, 1),
        direction=1,
        score=0.0,
    )
    assert sig.components == {}
    assert sig.above_threshold is False


# ---- load_weights ------------------------------------------------------


def test_load_weights_default_path_exists():
    assert DEFAULT_WEIGHTS_PATH.exists(), f"missing {DEFAULT_WEIGHTS_PATH}"
    cfg = load_weights()
    assert "baseline" in cfg
    comps = cfg["baseline"]["components"]
    assert "trend_above_ema_50" in comps
    assert "dxy_alignment" in comps


def test_load_weights_custom_path(tmp_path: Path):
    custom = tmp_path / "w.json"
    custom.write_text(json.dumps({"baseline": {"components": {"trend_above_ema_50": 2.0}}}))
    cfg = load_weights(custom)
    assert cfg["baseline"]["components"]["trend_above_ema_50"] == 2.0


def test_strategy_rejects_missing_block(tmp_path: Path):
    bad = tmp_path / "w.json"
    bad.write_text(json.dumps({"other_strategy": {}}))
    with pytest.raises(ValueError, match="no 'baseline' strategy block"):
        BaselineStrategy(weights=load_weights(bad))


# ---- Construction ------------------------------------------------------


def test_baseline_exposes_component_weights():
    strat = BaselineStrategy()
    cw = strat.component_weights
    assert cw["trend_supertrend_up"] == 1.5
    # Returned dict is a copy — mutating doesn't corrupt internal state
    cw["trend_supertrend_up"] = 999.0
    assert strat.component_weights["trend_supertrend_up"] == 1.5


def test_baseline_picks_up_threshold():
    strat = BaselineStrategy()
    assert strat.min_score_threshold == 3.0


# ---- score_pair: basic shape ------------------------------------------


def test_score_pair_requires_timestamp_column():
    df = pd.DataFrame({"open_bid": [1.0]})
    with pytest.raises(ValueError, match="timestamp"):
        BaselineStrategy().score_pair(df, symbol="EUR_USD")


def test_score_pair_empty_df_returns_empty():
    df = pd.DataFrame(
        {"timestamp": [], "open_bid": [], "open_ask": [], "high_bid": [], "high_ask": [],
         "low_bid": [], "low_ask": [], "close_bid": [], "close_ask": []}
    )
    assert BaselineStrategy().score_pair(df, symbol="EUR_USD") == []


def test_score_pair_returns_one_signal_per_bar():
    df = _uptrend_pair_df(n=120)
    sigs = BaselineStrategy().score_pair(df, symbol="EUR_USD")
    assert len(sigs) == len(df)
    assert all(isinstance(s, Signal) for s in sigs)
    assert all(s.symbol == "EUR_USD" and s.strategy == "baseline" for s in sigs)


# ---- Rule-firing: steady uptrend triggers trend rules -----------------


def test_uptrend_fires_trend_rules_on_late_bars():
    """Late bars in a clean uptrend should fire most trend/momentum rules."""
    df = _uptrend_pair_df(n=200)
    sigs = BaselineStrategy().score_pair(df, symbol="EUR_USD")
    late = sigs[-5:]  # after all indicators have stabilised

    # Every late bar should fire EMA-50 (close > EMA)
    assert all("trend_above_ema_50" in s.components for s in late)
    # SuperTrend up
    assert all("trend_supertrend_up" in s.components for s in late)
    # Ichimoku above cloud
    assert all("trend_ichimoku_above_cloud" in s.components for s in late)
    # MACD bullish (histogram positive after steady rise)
    assert all("trend_macd_bullish" in s.components for s in late)
    # At least one late bar scores above threshold
    assert any(s.above_threshold for s in late)
    # Direction is long
    assert all(s.direction == 1 for s in late)


def test_downtrend_fires_bearish_trend_rules():
    df = _downtrend_pair_df(n=200)
    sigs = BaselineStrategy().score_pair(df, symbol="EUR_USD")
    late = sigs[-5:]
    for s in late:
        assert "trend_above_ema_50" not in s.components
        assert "trend_supertrend_up" not in s.components
        assert "trend_ichimoku_above_cloud" not in s.components
        assert "trend_below_ema_50" in s.components
        assert "trend_supertrend_down" in s.components
        assert "trend_ichimoku_below_cloud" in s.components
    assert any(s.direction == -1 and s.above_threshold for s in late)


# ---- Weight overrides: zero disables a rule ----------------------------


def test_zero_weight_disables_rule():
    """Setting a component's weight to 0 must suppress it from reported components."""
    weights = load_weights()
    weights["baseline"]["components"]["trend_supertrend_up"] = 0.0
    strat = BaselineStrategy(weights=weights)

    df = _uptrend_pair_df(n=200)
    sigs = strat.score_pair(df, symbol="EUR_USD")
    # No signal should report supertrend_up — even though the condition fires
    for s in sigs:
        assert "trend_supertrend_up" not in s.components


def test_custom_weight_changes_score():
    weights_a = load_weights()
    weights_b = load_weights()
    weights_b["baseline"]["components"]["trend_above_ema_50"] = 10.0
    df = _uptrend_pair_df(n=200)
    sig_a = BaselineStrategy(weights=weights_a).score_pair(df, symbol="EUR_USD")[-1]
    sig_b = BaselineStrategy(weights=weights_b).score_pair(df, symbol="EUR_USD")[-1]
    # With trend_above_ema_50 fired, boosting its weight to 10.0 adds ~9.0
    assert sig_b.score > sig_a.score + 8.0


# ---- Absent context handled gracefully --------------------------------


def test_missing_dxy_and_strengths_does_not_crash():
    df = _uptrend_pair_df(n=120)
    sigs = BaselineStrategy().score_pair(df, symbol="EUR_USD")
    # Context rules must NOT fire when dxy/strengths weren't passed
    for s in sigs:
        assert "strength_base_strong" not in s.components
        assert "strength_quote_weak" not in s.components
        assert "dxy_alignment" not in s.components


def test_dxy_alignment_fires_on_usd_quote_with_falling_dxy():
    df = _uptrend_pair_df(n=200)
    # A falling DXY series aligned to the pair's timestamps
    n = len(df)
    dxy_vals = np.linspace(105.0, 95.0, n)
    dxy = pd.Series(dxy_vals, index=pd.DatetimeIndex(df["timestamp"]))
    sigs = BaselineStrategy().score_pair(df, symbol="EUR_USD", dxy=dxy)
    # Late bars should fire the DXY alignment rule (EUR_USD is a USD-quote pair)
    late = sigs[-5:]
    assert all("dxy_alignment" in s.components for s in late)


def test_dxy_alignment_silent_on_non_usd_cross():
    df = _uptrend_pair_df(n=200)
    n = len(df)
    dxy = pd.Series(np.linspace(105.0, 95.0, n), index=pd.DatetimeIndex(df["timestamp"]))
    sigs = BaselineStrategy().score_pair(df, symbol="EUR_GBP", dxy=dxy)
    # Non-USD cross → DXY rule should never fire
    for s in sigs:
        assert "dxy_alignment" not in s.components


def test_strength_rules_fire_when_base_strong():
    df = _uptrend_pair_df(n=120)
    n = len(df)
    # Construct a strengths frame where EUR is strongest, USD is weakest
    ccys = ["USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF"]
    # EUR gets highest strength rank
    strengths = pd.DataFrame(
        {
            "USD": np.full(n, -1.0),
            "EUR": np.full(n, 1.0),
            "GBP": np.full(n, 0.2),
            "JPY": np.full(n, 0.1),
            "AUD": np.full(n, 0.0),
            "NZD": np.full(n, -0.1),
            "CAD": np.full(n, -0.2),
            "CHF": np.full(n, -0.3),
        },
        index=pd.DatetimeIndex(df["timestamp"]),
    )
    sigs = BaselineStrategy().score_pair(df, symbol="EUR_USD", strengths=strengths)
    late = sigs[-5:]
    # Base (EUR) is rank 8 of 8 → in top 3 → fires
    assert all("strength_base_strong" in s.components for s in late)
    # Quote (USD) is rank 1 → in bottom 3 → fires
    assert all("strength_quote_weak" in s.components for s in late)
    assert ccys  # sanity — keep linter happy, confirms the list is built


# ---- score = sum(components) invariant --------------------------------


def test_score_equals_sum_of_components():
    df = _uptrend_pair_df(n=200)
    sigs = BaselineStrategy().score_pair(df, symbol="EUR_USD")
    for s in sigs:
        assert s.score == pytest.approx(sum(s.components.values()))


def test_above_threshold_matches_score():
    df = _uptrend_pair_df(n=200)
    strat = BaselineStrategy()
    sigs = strat.score_pair(df, symbol="EUR_USD")
    for s in sigs:
        assert s.above_threshold == (s.score > strat.min_score_threshold)


# ---- Smoke: real EUR_USD data from FxStore ---------------------------


def test_strategy_runs_on_real_eurusd_slice():
    from bh_ftmo.data.fx_store import FxStore

    store = FxStore(read_only=True)
    try:
        df = store.load(
            "EUR_USD",
            granularity="H4",
            start=pd.Timestamp("2025-01-01").to_pydatetime(),
            end=pd.Timestamp("2025-02-01").to_pydatetime(),
        )
    finally:
        store.close()

    if len(df) < 100:
        pytest.skip("fx_4h.duckdb EUR_USD slice too short")

    sigs = BaselineStrategy().score_pair(df, symbol="EUR_USD")
    assert len(sigs) == len(df)
    # Components dict contains only known rule keys
    known = set(BaselineStrategy().component_weights.keys())
    for s in sigs:
        assert set(s.components.keys()).issubset(known)
    # Score is finite
    assert all(np.isfinite(s.score) for s in sigs)
