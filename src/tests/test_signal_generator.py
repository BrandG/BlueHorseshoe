"""Tests for bh_ftmo.analysis.signal_generator."""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from bh_ftmo.analysis import (
    BaselineStrategy,
    Signal,
    SignalContext,
    SignalGenerator,
)
from bh_ftmo.analysis.signal_generator import (
    DEFAULT_STRENGTH_PAIRS,
    DXY_CONSTITUENTS,
    MIN_STRENGTH_PAIRS,
)


# ---- helpers -----------------------------------------------------------


def _trend_pair_df(start: float, slope: float, n: int = 200) -> pd.DataFrame:
    base_ts = datetime(2025, 1, 6, 0, 0, 0)
    closes = np.linspace(start, start * (1.0 + slope), n)
    highs = closes * 1.0005
    lows = closes * 0.9995
    opens = np.concatenate([[closes[0]], closes[:-1]])
    rows = []
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


def _full_universe(n: int = 200) -> dict[str, pd.DataFrame]:
    """Build trending DataFrames for every DXY constituent + strength pair."""
    seeds = {
        "EUR_USD": (1.10, 0.05),
        "GBP_USD": (1.30, 0.04),
        "AUD_USD": (0.70, 0.03),
        "NZD_USD": (0.65, 0.03),
        "USD_JPY": (150.0, -0.04),
        "USD_CHF": (0.90, -0.03),
        "USD_CAD": (1.35, -0.02),
        "USD_SEK": (10.5, -0.02),
        "EUR_GBP": (0.85, 0.01),
        "EUR_JPY": (165.0, 0.01),
        "EUR_CHF": (0.99, 0.02),
        "EUR_AUD": (1.57, 0.01),
        "EUR_CAD": (1.49, 0.02),
        "GBP_JPY": (195.0, 0.01),
        "GBP_CHF": (1.17, 0.02),
        "GBP_CAD": (1.76, 0.02),
        "AUD_JPY": (105.0, -0.01),
        "AUD_NZD": (1.07, 0.0),
        "NZD_JPY": (97.0, -0.01),
        "CHF_JPY": (167.0, -0.01),
        "CAD_JPY": (111.0, -0.02),
    }
    return {sym: _trend_pair_df(start, slope, n) for sym, (start, slope) in seeds.items()}


# ---- construction ------------------------------------------------------


def test_default_strategies_are_baseline():
    gen = SignalGenerator()
    assert len(gen.strategies) == 1
    assert isinstance(gen.strategies[0], BaselineStrategy)


def test_default_pair_lists_make_sense():
    # All six DXY constituents present
    assert set(DXY_CONSTITUENTS) == {
        "EUR_USD", "USD_JPY", "GBP_USD", "USD_CAD", "USD_SEK", "USD_CHF"
    }
    # Strength pair list covers every G8 currency at least three times
    counts: dict[str, int] = {}
    for p in DEFAULT_STRENGTH_PAIRS:
        b, q = p.split("_")
        counts[b] = counts.get(b, 0) + 1
        counts[q] = counts.get(q, 0) + 1
    for ccy in ("USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF"):
        assert counts.get(ccy, 0) >= 3, f"{ccy} only in {counts.get(ccy)} pairs"


# ---- context: DXY ------------------------------------------------------


def test_dxy_context_built_when_all_constituents_present():
    pair_dfs = _full_universe(n=120)
    ctx = SignalGenerator().build_context(pair_dfs)
    assert ctx.dxy is not None
    assert isinstance(ctx.dxy.index, pd.DatetimeIndex)
    assert len(ctx.dxy) == 120
    assert ctx.dxy_pairs_used == DXY_CONSTITUENTS


def test_dxy_context_absent_when_constituent_missing():
    pair_dfs = _full_universe(n=120)
    pair_dfs.pop("USD_SEK")  # drop one constituent
    ctx = SignalGenerator().build_context(pair_dfs)
    assert ctx.dxy is None
    assert ctx.dxy_pairs_used == ()


# ---- context: strengths -----------------------------------------------


def test_strengths_context_built_when_enough_pairs():
    pair_dfs = _full_universe(n=120)
    ctx = SignalGenerator().build_context(pair_dfs)
    assert ctx.strengths is not None
    assert isinstance(ctx.strengths.index, pd.DatetimeIndex)
    # All G8 currencies represented as columns
    assert set(ctx.strengths.columns) == {"USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF"}


def test_strengths_context_absent_when_too_few_pairs():
    pair_dfs = {"EUR_USD": _trend_pair_df(1.10, 0.05, 120)}  # only 1 strength pair
    ctx = SignalGenerator().build_context(pair_dfs)
    assert ctx.strengths is None


def test_strengths_context_built_with_minimum_pairs():
    # Pick exactly MIN_STRENGTH_PAIRS pairs
    seeds = {
        "EUR_USD": (1.10, 0.05),
        "GBP_USD": (1.30, 0.04),
        "USD_JPY": (150.0, -0.04),
        "USD_CHF": (0.90, -0.03),
    }
    assert len(seeds) == MIN_STRENGTH_PAIRS
    pair_dfs = {sym: _trend_pair_df(s, sl, 120) for sym, (s, sl) in seeds.items()}
    ctx = SignalGenerator().build_context(pair_dfs)
    assert ctx.strengths is not None


# ---- generate ----------------------------------------------------------


def test_generate_one_signal_per_bar_per_pair_per_strategy():
    pair_dfs = _full_universe(n=100)
    sigs = SignalGenerator().generate(pair_dfs)
    # 1 strategy × N pairs × 100 bars
    assert len(sigs) == len(pair_dfs) * 100
    symbols_seen = {s.symbol for s in sigs}
    assert symbols_seen == set(pair_dfs.keys())


def test_generate_respects_symbols_filter():
    pair_dfs = _full_universe(n=100)
    sigs = SignalGenerator().generate(pair_dfs, symbols=["EUR_USD", "GBP_USD"])
    assert {s.symbol for s in sigs} == {"EUR_USD", "GBP_USD"}
    assert len(sigs) == 2 * 100


def test_generate_skips_missing_or_empty_symbols():
    pair_dfs = _full_universe(n=100)
    sigs = SignalGenerator().generate(pair_dfs, symbols=["EUR_USD", "DOES_NOT_EXIST"])
    assert {s.symbol for s in sigs} == {"EUR_USD"}


def test_generate_supplies_dxy_to_strategies():
    """When DXY is available, the dxy_alignment rule should fire on USD-side trending pairs."""
    pair_dfs = _full_universe(n=200)
    sigs = SignalGenerator().generate(pair_dfs, symbols=["EUR_USD"])
    # EUR_USD is rising AND USD_JPY/CHF/CAD/SEK are falling → DXY is falling →
    # alignment fires for late EUR_USD bars (USD-quote pair, falling DXY)
    late = sigs[-5:]
    assert any("dxy_alignment" in s.components for s in late)


def test_generate_supplies_strengths_to_strategies():
    pair_dfs = _full_universe(n=200)
    sigs = SignalGenerator().generate(pair_dfs, symbols=["EUR_USD"])
    late = sigs[-5:]
    # EUR is the strongest currency in the synthetic universe; USD is weakest
    assert any("strength_base_strong" in s.components for s in late)
    assert any("strength_quote_weak" in s.components for s in late)


def test_generate_without_context_pairs_runs_cleanly():
    """Generator must not crash if only a single pair is supplied."""
    pair_dfs = {"EUR_USD": _trend_pair_df(1.10, 0.05, 120)}
    sigs = SignalGenerator().generate(pair_dfs)
    assert len(sigs) == 120
    # Context rules must NOT fire (no DXY, no strengths available)
    for s in sigs:
        assert "dxy_alignment" not in s.components
        assert "strength_base_strong" not in s.components
        assert "strength_quote_weak" not in s.components


# ---- multi-strategy ----------------------------------------------------


class _DummyStrategy:
    """Constant-score strategy so we can verify fan-out without indicator math."""
    name = "dummy"

    def score_pair(self, pair_df, *, symbol, dxy=None, strengths=None):
        return [
            Signal(
                symbol=symbol,
                strategy=self.name,
                timestamp=ts,
                direction=1,
                score=1.0,
                components={"always": 1.0},
                above_threshold=True,
            )
            for ts in pair_df["timestamp"]
        ]


def test_multiple_strategies_each_emit_signals():
    pair_dfs = _full_universe(n=50)
    gen = SignalGenerator(strategies=[BaselineStrategy(), _DummyStrategy()])
    sigs = gen.generate(pair_dfs, symbols=["EUR_USD"])
    strategies_seen = {s.strategy for s in sigs}
    assert strategies_seen == {"baseline", "dummy"}
    # 2 strategies × 50 bars
    assert len(sigs) == 100


# ---- to_dataframe ------------------------------------------------------


def test_to_dataframe_shape_and_columns():
    pair_dfs = _full_universe(n=50)
    sigs = SignalGenerator().generate(pair_dfs, symbols=["EUR_USD", "GBP_USD"])
    df = SignalGenerator.to_dataframe(sigs)
    assert len(df) == len(sigs)
    expected_cols = {"timestamp", "symbol", "strategy", "direction", "score", "above_threshold", "components"}
    assert expected_cols.issubset(set(df.columns))


def test_to_dataframe_empty_input():
    df = SignalGenerator.to_dataframe([])
    assert len(df) == 0


# ---- generate_from_store ----------------------------------------------


def test_generate_from_store_smoke():
    from bh_ftmo.data.fx_store import FxStore

    store = FxStore(read_only=True)
    try:
        sigs = SignalGenerator().generate_from_store(
            store,
            symbols=["EUR_USD", "GBP_USD"],
            granularity="H4",
            start=pd.Timestamp("2025-01-01").to_pydatetime(),
            end=pd.Timestamp("2025-02-01").to_pydatetime(),
        )
    finally:
        store.close()

    if not sigs:
        pytest.skip("fx_4h.duckdb empty for this slice")
    symbols_seen = {s.symbol for s in sigs}
    assert symbols_seen.issubset({"EUR_USD", "GBP_USD"})
    # Real data should produce both symbols if store covers Jan 2025
    if len(sigs) > 100:
        assert symbols_seen == {"EUR_USD", "GBP_USD"}
