"""Tests for bh_ftmo.analysis.mean_reversion."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from bh_ftmo.analysis import MeanReversionStrategy, Signal, load_weights


# ---- helpers -----------------------------------------------------------


def _build_pair_df(closes: list[float]) -> pd.DataFrame:
    """Build a BA-format pair DataFrame from a close-price series.

    Spread is zero (bid == ask), high/low are tight around close. Suitable
    for exercising MR rules without indicator artefacts from large bar
    bodies.
    """
    base_ts = datetime(2025, 1, 6, 0, 0, 0)  # Monday 00:00 UTC
    closes_arr = np.asarray(closes, dtype=float)
    highs = closes_arr * 1.0003
    lows = closes_arr * 0.9997
    opens = np.concatenate([[closes_arr[0]], closes_arr[:-1]])
    rows = []
    for i in range(len(closes_arr)):
        rows.append(
            {
                "timestamp": base_ts + timedelta(hours=4 * i),
                "open_bid": opens[i], "open_ask": opens[i],
                "high_bid": highs[i], "high_ask": highs[i],
                "low_bid": lows[i], "low_ask": lows[i],
                "close_bid": closes_arr[i], "close_ask": closes_arr[i],
            }
        )
    return pd.DataFrame(rows)


def _flat_then_drop(n_flat: int = 60, n_drop: int = 20, base: float = 1.1000) -> pd.DataFrame:
    """Build a price series that holds flat then drops sharply.

    The drop pushes RSI < 30, Williams %R < -80, CCI < -100, and forces
    close below BB.lower band — the canonical "long mean reversion" setup.
    """
    flat = [base] * n_flat
    drop = list(np.linspace(base, base * 0.97, n_drop))
    return _build_pair_df(flat + drop)


def _flat_then_spike(n_flat: int = 60, n_spike: int = 20, base: float = 1.1000) -> pd.DataFrame:
    """Mirror of _flat_then_drop — climbs sharply to trigger overbought rules."""
    flat = [base] * n_flat
    spike = list(np.linspace(base, base * 1.03, n_spike))
    return _build_pair_df(flat + spike)


# ---- construction ------------------------------------------------------


def test_constructor_loads_weights_block():
    strat = MeanReversionStrategy()
    cw = strat.component_weights
    assert "mr_rsi_oversold" in cw
    assert "mr_above_bb_upper" in cw
    assert strat.min_score_threshold == 3.0


def test_rejects_missing_block(tmp_path: Path):
    bad = tmp_path / "w.json"
    bad.write_text(json.dumps({"baseline": {}}))
    with pytest.raises(ValueError, match="no 'mean_reversion' strategy block"):
        MeanReversionStrategy(weights=load_weights(bad))


def test_component_weights_returns_copy():
    strat = MeanReversionStrategy()
    cw = strat.component_weights
    cw["mr_rsi_oversold"] = 999.0
    assert strat.component_weights["mr_rsi_oversold"] != 999.0


# ---- score_pair: shape -------------------------------------------------


def test_requires_timestamp_column():
    df = pd.DataFrame({"open_bid": [1.0]})
    with pytest.raises(ValueError, match="timestamp"):
        MeanReversionStrategy().score_pair(df, symbol="EUR_USD")


def test_empty_df_returns_empty():
    df = pd.DataFrame(
        {"timestamp": [], "open_bid": [], "open_ask": [], "high_bid": [], "high_ask": [],
         "low_bid": [], "low_ask": [], "close_bid": [], "close_ask": []}
    )
    assert MeanReversionStrategy().score_pair(df, symbol="EUR_USD") == []


def test_one_signal_per_bar():
    df = _flat_then_drop()
    sigs = MeanReversionStrategy().score_pair(df, symbol="EUR_USD")
    assert len(sigs) == len(df)
    assert all(isinstance(s, Signal) for s in sigs)
    assert all(s.strategy == "mean_reversion" for s in sigs)


# ---- direction resolution ---------------------------------------------


def test_flat_market_emits_zero_direction_signals():
    """A pure flat market has no MR setups — every signal should be direction=0."""
    df = _build_pair_df([1.10] * 100)
    sigs = MeanReversionStrategy().score_pair(df, symbol="EUR_USD")
    # Note: tiny synthetic noise in highs/lows could occasionally trigger an indicator
    # near boundaries; assert overwhelmingly direction=0
    zero_count = sum(1 for s in sigs if s.direction == 0)
    assert zero_count > 0.9 * len(sigs)
    # No signal should pass threshold on a flat market
    assert not any(s.above_threshold for s in sigs)


def test_oversold_drop_fires_long_signal():
    df = _flat_then_drop()
    sigs = MeanReversionStrategy().score_pair(df, symbol="EUR_USD")
    # Some bar near the end of the drop should be a long MR setup
    long_above = [s for s in sigs if s.direction == +1 and s.above_threshold]
    assert long_above, "expected at least one long mean-reversion signal"
    # Validate components on the strongest long signal
    best = max(long_above, key=lambda s: s.score)
    expected_anchors = {
        "mr_rsi_oversold",
        "mr_below_bb_lower",
        "mr_williams_oversold",
        "mr_cci_extreme_low",
    }
    fired = set(best.components.keys()) & expected_anchors
    assert fired, f"no oversold anchors fired: {best.components}"


def test_overbought_spike_fires_short_signal():
    df = _flat_then_spike()
    sigs = MeanReversionStrategy().score_pair(df, symbol="EUR_USD")
    short_above = [s for s in sigs if s.direction == -1 and s.above_threshold]
    assert short_above, "expected at least one short mean-reversion signal"
    best = max(short_above, key=lambda s: s.score)
    expected_anchors = {
        "mr_rsi_overbought",
        "mr_above_bb_upper",
        "mr_williams_overbought",
        "mr_cci_extreme_high",
    }
    fired = set(best.components.keys()) & expected_anchors
    assert fired, f"no overbought anchors fired: {best.components}"


# ---- direction-only-rules respect direction ---------------------------


def test_long_signals_never_carry_short_specific_rules():
    df = _flat_then_drop()
    sigs = MeanReversionStrategy().score_pair(df, symbol="EUR_USD")
    for s in sigs:
        if s.direction == +1:
            assert "mr_rsi_overbought" not in s.components
            assert "mr_above_bb_upper" not in s.components
            assert "mr_williams_overbought" not in s.components
            assert "mr_cci_extreme_high" not in s.components
            assert "mr_bearish_reversal_candle" not in s.components


def test_short_signals_never_carry_long_specific_rules():
    df = _flat_then_spike()
    sigs = MeanReversionStrategy().score_pair(df, symbol="EUR_USD")
    for s in sigs:
        if s.direction == -1:
            assert "mr_rsi_oversold" not in s.components
            assert "mr_below_bb_lower" not in s.components
            assert "mr_williams_oversold" not in s.components
            assert "mr_cci_extreme_low" not in s.components
            assert "mr_bullish_reversal_candle" not in s.components


# ---- weight overrides --------------------------------------------------


def test_zero_weight_disables_rule():
    weights = load_weights()
    weights["mean_reversion"]["components"]["mr_rsi_oversold"] = 0.0
    strat = MeanReversionStrategy(weights=weights)
    df = _flat_then_drop()
    sigs = strat.score_pair(df, symbol="EUR_USD")
    for s in sigs:
        assert "mr_rsi_oversold" not in s.components


def test_zero_weight_anchor_doesnt_block_direction():
    """Disabling RSI oversold should not prevent the signal from firing if
    other anchors (BB, Williams, CCI) still fire."""
    weights = load_weights()
    weights["mean_reversion"]["components"]["mr_rsi_oversold"] = 0.0
    strat = MeanReversionStrategy(weights=weights)
    df = _flat_then_drop()
    sigs = strat.score_pair(df, symbol="EUR_USD")
    # Some bar should still be direction=+1 (other anchors carrying it)
    assert any(s.direction == +1 for s in sigs)


# ---- score = sum invariant --------------------------------------------


def test_score_equals_sum_of_components():
    df = _flat_then_drop()
    sigs = MeanReversionStrategy().score_pair(df, symbol="EUR_USD")
    for s in sigs:
        assert s.score == pytest.approx(sum(s.components.values()))


def test_no_signal_has_empty_components_and_zero_score():
    df = _flat_then_drop()
    sigs = MeanReversionStrategy().score_pair(df, symbol="EUR_USD")
    for s in sigs:
        if s.direction == 0:
            assert s.components == {}
            assert s.score == 0.0
            assert not s.above_threshold


# ---- API compat: dxy/strengths accepted but ignored -------------------


def test_accepts_unused_context_args():
    df = _flat_then_drop()
    n = len(df)
    dxy = pd.Series(np.linspace(105, 95, n), index=pd.DatetimeIndex(df["timestamp"]))
    strengths = pd.DataFrame(
        {c: np.zeros(n) for c in ("USD", "EUR")},
        index=pd.DatetimeIndex(df["timestamp"]),
    )
    sigs = MeanReversionStrategy().score_pair(df, symbol="EUR_USD", dxy=dxy, strengths=strengths)
    assert len(sigs) == n


# ---- smoke: real EUR_USD data -----------------------------------------


def test_runs_on_real_eurusd_slice():
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

    sigs = MeanReversionStrategy().score_pair(df, symbol="EUR_USD")
    assert len(sigs) == len(df)
    known = set(MeanReversionStrategy().component_weights.keys())
    for s in sigs:
        assert set(s.components.keys()).issubset(known)
        assert s.direction in {-1, 0, +1}
        assert np.isfinite(s.score)


# ---- generator integration --------------------------------------------


def test_signal_generator_runs_both_strategies():
    from bh_ftmo.analysis import BaselineStrategy, SignalGenerator

    df = _flat_then_drop(n_flat=80, n_drop=30)
    gen = SignalGenerator(strategies=[BaselineStrategy(), MeanReversionStrategy()])
    sigs = gen.generate({"EUR_USD": df}, symbols=["EUR_USD"])
    strategies_seen = {s.strategy for s in sigs}
    assert strategies_seen == {"baseline", "mean_reversion"}
