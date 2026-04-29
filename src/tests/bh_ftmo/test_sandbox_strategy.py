"""Unit coverage for the sandbox_v1 event strategy."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from bh_ftmo.analysis import SandboxStrategy, load_weights


def _pair_df(
    closes: list[float] | np.ndarray,
    *,
    highs: list[float] | np.ndarray | None = None,
    lows: list[float] | np.ndarray | None = None,
) -> pd.DataFrame:
    base_ts = datetime(2025, 1, 6, 0, 0, 0)
    closes_arr = np.asarray(closes, dtype=float)
    highs_arr = (
        np.asarray(highs, dtype=float) if highs is not None else closes_arr * 1.0005
    )
    lows_arr = (
        np.asarray(lows, dtype=float) if lows is not None else closes_arr * 0.9995
    )
    opens = np.concatenate([[closes_arr[0]], closes_arr[:-1]])

    return pd.DataFrame(
        {
            "timestamp": [base_ts + timedelta(hours=4 * i) for i in range(len(closes_arr))],
            "open_bid": opens,
            "open_ask": opens,
            "high_bid": highs_arr,
            "high_ask": highs_arr,
            "low_bid": lows_arr,
            "low_ask": lows_arr,
            "close_bid": closes_arr,
            "close_ask": closes_arr,
        }
    )


def _weights_for(components: dict[str, float]) -> dict:
    weights = load_weights()
    weights["sandbox_v1"]["components"].update(components)
    return weights


def test_sma_cross_long_fires_on_golden_cross() -> None:
    closes = [1.20] * 30 + [1.00] * 30 + [1.45] * 30
    strategy = SandboxStrategy(weights=_weights_for({"sma_cross_long": 1.0}))

    signals = strategy.score_pair(_pair_df(closes), symbol="EUR_USD")
    cross_signals = [s for s in signals if "sma_cross_long" in s.components]

    assert cross_signals
    assert cross_signals[0].direction == +1
    assert cross_signals[0].score == 1.0
    assert cross_signals[0].above_threshold


def test_stoch_oversold_long_fires_on_recovery() -> None:
    closes = [10.0, 9.0, 9.0, 9.0, 9.6]
    highs = [10.0, 10.0, 10.0, 10.0, 10.0]
    lows = [9.0, 9.0, 9.0, 9.0, 9.0]
    strategy = SandboxStrategy(
        weights=_weights_for({"stoch_oversold_cross_long": 1.0}),
        stoch_period=3,
    )

    signals = strategy.score_pair(_pair_df(closes, highs=highs, lows=lows), symbol="EUR_USD")
    stoch_signals = [s for s in signals if "stoch_oversold_cross_long" in s.components]

    assert stoch_signals
    assert stoch_signals[0].direction == +1
    assert stoch_signals[0].score == 1.0


def test_rsi_overbought_short_fires_on_validated_pair() -> None:
    closes = [1.00] + list(np.linspace(1.01, 1.18, 18)) + [
        1.16,
        1.14,
        1.12,
        1.10,
    ]
    strategy = SandboxStrategy(weights=_weights_for({"rsi_overbought_cross_short": 1.0}))

    signals = strategy.score_pair(_pair_df(closes), symbol="USD_CHF")
    rsi_signals = [s for s in signals if "rsi_overbought_cross_short" in s.components]

    assert rsi_signals
    assert rsi_signals[0].direction == -1
    assert rsi_signals[0].score == 1.0


def test_rsi_overbought_short_blocked_on_non_validated_pair() -> None:
    closes = [1.00] + list(np.linspace(1.01, 1.18, 18)) + [
        1.16,
        1.14,
        1.12,
        1.10,
    ]
    strategy = SandboxStrategy(weights=_weights_for({"rsi_overbought_cross_short": 1.0}))

    signals = strategy.score_pair(_pair_df(closes), symbol="GBP_USD")

    assert all("rsi_overbought_cross_short" not in s.components for s in signals)
    assert all(s.direction == 0 for s in signals)


def test_no_signal_yields_zero_direction() -> None:
    closes = [1.10] * 80
    signals = SandboxStrategy().score_pair(_pair_df(closes), symbol="EUR_USD")

    assert all(s.direction == 0 for s in signals)
    assert all(s.score == 0.0 for s in signals)
    assert all(not s.above_threshold for s in signals)
    assert all(s.components == {} for s in signals)


def test_long_short_tie_resolves_long() -> None:
    closes = [1.00] + list(np.linspace(1.01, 1.18, 18)) + [
        1.17,
        1.15,
        1.13,
        1.11,
        1.09,
    ]
    highs = list(np.asarray(closes) + 0.30)
    lows = list(np.asarray(closes) - 0.30)
    highs[21] = closes[21] + 0.20
    lows[21] = closes[21] - 0.01
    highs[22] = closes[22] + 0.05
    lows[22] = closes[22] - 0.40
    df = _pair_df(closes, highs=highs, lows=lows)

    long_only = SandboxStrategy(
        weights=_weights_for({"stoch_oversold_cross_long": 1.0}),
        stoch_period=1,
        rsi_threshold=101.0,
    ).score_pair(df, symbol="USD_CHF")
    short_only = SandboxStrategy(
        weights=_weights_for({"rsi_overbought_cross_short": 1.0}),
        stoch_period=1,
        stoch_threshold=101.0,
    ).score_pair(df, symbol="USD_CHF")
    long_times = {s.timestamp for s in long_only if s.direction == +1}
    short_times = {s.timestamp for s in short_only if s.direction == -1}
    tie_times = long_times & short_times

    strategy = SandboxStrategy(
        weights=_weights_for(
            {
                "stoch_oversold_cross_long": 1.0,
                "rsi_overbought_cross_short": 1.0,
            }
        ),
        stoch_period=1,
    )

    signals = strategy.score_pair(df, symbol="USD_CHF")
    tie_signals = [s for s in signals if s.timestamp in tie_times]

    assert tie_times
    assert tie_signals
    assert tie_signals[0].direction == +1
    assert "stoch_oversold_cross_long" in tie_signals[0].components
    assert "rsi_overbought_cross_short" not in tie_signals[0].components


def test_sandbox_strategy_loads_weights() -> None:
    weights = load_weights()
    strategy = SandboxStrategy(weights=weights)

    assert strategy.min_score_threshold == 0.5
    assert strategy.component_weights == weights["sandbox_v1"]["components"]
    assert strategy.short_pair_whitelist == frozenset(
        {"CAD_JPY", "EUR_NOK", "USD_CAD", "USD_CHF"}
    )
