"""Behavioural tests for DeepDownAdxStrategy (the tracking-only adx_diDown sleeve).

Fires on a strong, DEEP established downtrend (ADX>thr & -DI>+DI for >= ADX_DOWN_MIN_RUN bars)
in a nonbull regime, on the inherited DeepOversold 2:1 ATR bracket. Tracking-only: paper_tradeable
is False so PaperTrader excludes it from live orders, but it still flows to the hypothesis engine.
"""
import numpy as np
import pandas as pd
import pytest

from bluehorseshoe.analysis.strategy import SwingTrader
from bluehorseshoe.analysis.strategy_interface import DeepDownAdxStrategy
from bluehorseshoe.analysis import constants as C


@pytest.fixture
def trader():
    return SwingTrader.__new__(SwingTrader)


def _frame(closes, volume=10_000_000.0):
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    return pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=n, freq="D").astype(str),
        "open": closes,
        "high": closes * 1.005,
        "low": closes * 0.995,
        "close": closes,
        "volume": np.full(n, volume, dtype=float),
    })


def _falling(n_fall, start=100.0, drop=0.01, warmup=30):
    path = list(np.linspace(start * 0.98, start, warmup))
    for _ in range(n_fall):
        path.append(path[-1] * (1 - drop))
    return path


def _spy_frame(bull: bool):
    if bull:
        closes = [100.0 * (1.004 ** i) for i in range(260)]
    else:
        closes = list(np.linspace(180.0, 100.0, 260))
    return _frame(closes)


class TestDowntrendRunHelper:
    def test_full_run(self):
        adx = np.full(8, 30.0); pdi = np.full(8, 10.0); mdi = np.full(8, 20.0)
        assert DeepDownAdxStrategy._downtrend_run(adx, pdi, mdi, 25.0) == 8

    def test_breaks_when_recent_not_downtrend(self):
        adx = np.full(8, 30.0); pdi = np.full(8, 10.0)
        mdi = np.array([20, 20, 20, 20, 20, 5, 5, 5], float)  # last 3 have -DI < +DI
        assert DeepDownAdxStrategy._downtrend_run(adx, pdi, mdi, 25.0) == 0

    def test_breaks_when_adx_below_threshold(self):
        adx = np.array([30, 30, 30, 30, 30, 30, 30, 10], float)
        pdi = np.full(8, 10.0); mdi = np.full(8, 20.0)
        assert DeepDownAdxStrategy._downtrend_run(adx, pdi, mdi, 25.0) == 0

    def test_partial_run_counts_only_trailing(self):
        adx = np.full(8, 30.0)
        pdi = np.full(8, 10.0)
        mdi = np.array([5, 5, 5, 5, 20, 20, 20, 20], float)  # last 4 downtrend
        assert DeepDownAdxStrategy._downtrend_run(adx, pdi, mdi, 25.0) == 4

    def test_leading_nan_ignored(self):
        adx = np.array([np.nan, np.nan, 30, 30, 30, 30, 30, 30], float)
        pdi = np.full(8, 10.0); mdi = np.full(8, 20.0)
        assert DeepDownAdxStrategy._downtrend_run(adx, pdi, mdi, 25.0) == 6


class TestGatesAndFiring:
    def test_fires_on_deep_nonbull_downtrend(self, trader):
        strat = DeepDownAdxStrategy()
        df = _frame(_falling(n_fall=40))
        res = strat.process_worker(
            trader, df, "X", {}, {"benchmark_df": _spy_frame(bull=False)}, {}, 0.0)
        assert res is not None
        assert res.components["downtrend_run"] >= C.ADX_DOWN_MIN_RUN
        s = res.setup
        assert s["stop_loss"] < s["entry_price"] < s["take_profit"]
        assert res.score >= C.ADX_DOWN_BASE_SCORE

    def test_bull_regime_blocks(self, trader):
        strat = DeepDownAdxStrategy()
        df = _frame(_falling(n_fall=40))
        res = strat.process_worker(
            trader, df, "X", {}, {"benchmark_df": _spy_frame(bull=True)}, {}, 0.0)
        assert res is None

    def test_missing_spy_fails_closed(self, trader):
        strat = DeepDownAdxStrategy()
        df = _frame(_falling(n_fall=40))
        assert strat.process_worker(trader, df, "X", {}, {"benchmark_df": None}, {}, 0.0) is None

    def test_uptrend_does_not_fire(self, trader):
        strat = DeepDownAdxStrategy()
        df = _frame([100.0 * (1.01 ** i) for i in range(70)])  # +DI dominant → never a downtrend bar
        res = strat.process_worker(
            trader, df, "X", {}, {"benchmark_df": _spy_frame(bull=False)}, {}, 0.0)
        assert res is None

    def test_tracking_only(self):
        assert DeepDownAdxStrategy().paper_tradeable is False
