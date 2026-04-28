"""Regression coverage for BaselineStrategy per-bar two-sided direction."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from bh_ftmo.analysis import BaselineStrategy, load_weights


def _pair_df_from_closes(closes: list[float] | np.ndarray) -> pd.DataFrame:
    base_ts = datetime(2025, 1, 6, 0, 0, 0)
    closes_arr = np.asarray(closes, dtype=float)
    highs = closes_arr * 1.0005
    lows = closes_arr * 0.9995
    opens = np.concatenate([[closes_arr[0]], closes_arr[:-1]])

    return pd.DataFrame(
        {
            "timestamp": [base_ts + timedelta(hours=4 * i) for i in range(len(closes_arr))],
            "open_bid": opens,
            "open_ask": opens,
            "high_bid": highs,
            "high_ask": highs,
            "low_bid": lows,
            "low_ask": lows,
            "close_bid": closes_arr,
            "close_ask": closes_arr,
        }
    )


def _weights_with_components(components: dict[str, float], threshold: float = 3.0) -> dict:
    weights = load_weights()
    weights["baseline"]["min_score_threshold"] = threshold
    weights["baseline"]["components"] = {
        key: 0.0 for key in weights["baseline"]["components"]
    } | components
    return weights


def test_baseline_emits_long_on_clearly_bullish_fixture() -> None:
    closes = np.linspace(1.1000, 1.1700, 220)
    sigs = BaselineStrategy().score_pair(_pair_df_from_closes(closes), symbol="EUR_USD")

    assert any(s.direction == +1 and s.above_threshold for s in sigs)
    assert not any(s.direction == -1 for s in sigs)


def test_baseline_emits_short_on_clearly_bearish_fixture() -> None:
    closes = np.linspace(1.2000, 1.1300, 220)
    sigs = BaselineStrategy().score_pair(_pair_df_from_closes(closes), symbol="EUR_USD")

    assert any(s.direction == -1 and s.above_threshold for s in sigs)
    assert not any(s.direction == +1 for s in sigs)


def test_baseline_emits_zero_on_choppy_fixture() -> None:
    closes = 1.1000 + np.sin(np.linspace(0, 10 * np.pi, 140)) * 0.0002
    weights = load_weights()
    weights["baseline"]["min_score_threshold"] = 99.0
    sigs = BaselineStrategy(weights=weights).score_pair(
        _pair_df_from_closes(closes),
        symbol="EUR_USD",
    )

    assert all(s.direction == 0 for s in sigs)
    assert all(not s.above_threshold for s in sigs)
    assert all(s.components == {} for s in sigs)


def test_baseline_picks_higher_score_when_both_sides_fire() -> None:
    closes = 1.1000 + np.sin(np.linspace(0, 16 * np.pi, 160)) * 0.0008
    df = _pair_df_from_closes(closes)

    short_wins = _weights_with_components(
        {
            "momentum_rsi_healthy": 1.0,
            "momentum_rsi_healthy_short": 3.0,
        },
        threshold=0.5,
    )
    short_sigs = BaselineStrategy(weights=short_wins).score_pair(df, symbol="EUR_USD")
    both_sides_short = [
        s
        for s in short_sigs
        if "momentum_rsi_healthy" in s.components
        or "momentum_rsi_healthy_short" in s.components
    ]
    assert any(s.direction == -1 for s in both_sides_short)

    tied = _weights_with_components(
        {
            "momentum_rsi_healthy": 1.0,
            "momentum_rsi_healthy_short": 1.0,
        },
        threshold=0.5,
    )
    tied_sigs = BaselineStrategy(weights=tied).score_pair(df, symbol="EUR_USD")
    tie_bars = [
        s
        for s in tied_sigs
        if "momentum_rsi_healthy" in s.components
        or "momentum_rsi_healthy_short" in s.components
    ]
    assert any(s.direction == +1 for s in tie_bars)
