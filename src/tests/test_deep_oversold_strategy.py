"""Behavioural tests for DeepOversoldStrategy.

The strategy is mechanical and ML-free: it fires only when RSI(14) has been below
30 for >= DEEP_OVERSOLD_MIN_AGE consecutive bars AND 20d avg dollar-volume clears
the floor. These tests build synthetic OHLCV frames that put RSI in known states
and assert the gates (age, liquidity, no-signal) behave.
"""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from bluehorseshoe.analysis.strategy import SwingTrader
from bluehorseshoe.analysis.strategy_interface import DeepOversoldHAStrategy, DeepOversoldStrategy
from bluehorseshoe.analysis import constants as C


@pytest.fixture
def trader():
    # __new__ bypasses __init__ (no DB) — same pattern workers use. We only need
    # the pure-math calculate_mean_reversion_setup / _calculate_atr methods.
    return SwingTrader.__new__(SwingTrader)


def _frame(closes, volume=5_000_000.0, price_scale=1.0):
    """Build an OHLCV frame from a close path; high/low straddle close by 0.5%.

    Straddle kept tight so ATR/price stays under MAX_RISK_PERCENT (5%) — otherwise
    the realistic 1*ATR stop trips ``is_realistic`` and the setup is rejected.
    """
    closes = np.asarray(closes, dtype=float) * price_scale
    n = len(closes)
    return pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=n, freq="D").astype(str),
        "open": closes,
        "high": closes * 1.005,
        "low": closes * 0.995,
        "close": closes,
        "volume": np.full(n, volume, dtype=float),
    })


def _falling_then_floor(n_fall, floor_len, start=100.0, drop=0.01, warmup=30):
    """Gentle rise (RSI neutral) → sustained 1%/day decline (drives RSI<30) → flat floor.

    The warmup guarantees >= 40 bars (the strategy's minimum) and a neutral RSI
    before the decline, so oversold *age* scales with ``n_fall``.
    """
    path = list(np.linspace(start * 0.98, start, warmup))
    for _ in range(n_fall):
        path.append(path[-1] * (1 - drop))
    path += [path[-1]] * floor_len
    return path


def _spy_frame(bull=True):
    """SPY history that deterministically trips the EMA nonbull helper."""
    if bull:
        closes = [100.0] * 220 + [120.0] * 30
    else:
        closes = [120.0] * 220 + [90.0] * 30
    return _frame(closes, volume=10_000_000)


def _ctx(**kwargs):
    defaults = {
        "market_health": {"status": "Bearish"},
        "benchmark_df": None,
        "solvency": {},
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _config(nonbull=False, solvency=False):
    return SimpleNamespace(
        deep_oversold_nonbull_gate=nonbull,
        deep_oversold_solvency_filter=solvency,
    )


class TestDeepOversoldGates:

    def test_fires_on_persistent_oversold_liquid(self, trader):
        strat = DeepOversoldStrategy()
        # Long steady decline → RSI pinned well below 30 for many consecutive bars.
        df = _frame(_falling_then_floor(n_fall=40, floor_len=0), volume=10_000_000, price_scale=1.0)
        res = strat._evaluate(trader, df, regime_status="Bearish")
        assert res is not None
        assert res.components["oversold_age"] >= C.DEEP_OVERSOLD_MIN_AGE
        assert res.components["rsi"] < C.DEEP_OVERSOLD_RSI_THRESHOLD
        # 2:1 geometry: target ~2*ATR above, stop ~1*ATR below entry.
        s = res.setup
        assert s["stop_loss"] < s["entry_price"] < s["take_profit"]
        assert res.score >= C.DEEP_OVERSOLD_BASE_SCORE

    def test_entry_uses_premium_above_close_with_anchored_2to1(self, trader):
        strat = DeepOversoldStrategy()
        closes = _falling_then_floor(n_fall=40, floor_len=0)
        df = _frame(closes, volume=10_000_000)
        res = strat._evaluate(trader, df, regime_status="Bearish")
        assert res is not None
        last_close = df["close"].iloc[-1]
        # entry sits the configured premium above the prior close
        assert res.setup["entry_price"] == pytest.approx(
            last_close * (1 + C.DEEP_OVERSOLD_ENTRY_PREMIUM), rel=1e-6)
        # stop/target anchored to entry → ~2:1 (minus the 2% target haircut)
        s = res.setup
        assert s["rr_ratio"] == pytest.approx(2.0 * 0.98, rel=1e-3)
        assert s["actual_close"] == pytest.approx(last_close, rel=1e-9)

    def test_no_signal_when_not_oversold(self, trader):
        strat = DeepOversoldStrategy()
        # Steady uptrend → RSI high, age 0.
        df = _frame([100.0 * (1.01 ** i) for i in range(60)], volume=10_000_000)
        assert strat._evaluate(trader, df, regime_status="Bullish") is None

    def test_liquidity_floor_rejects_thin_names(self, trader):
        strat = DeepOversoldStrategy()
        # Same oversold path (passes age + is_realistic + price gates), but
        # dollar-volume below the $25M floor so LIQUIDITY is the gate that trips.
        # price ends ~$67, volume 200k → ~$13M < $25M floor.
        df = _frame(_falling_then_floor(n_fall=40, floor_len=0), volume=200_000.0)
        assert strat._evaluate(trader, df, regime_status="Bearish") is None

    def test_age_ranks_score_monotonically(self, trader):
        """Deeper/longer oversold → higher score (the validated ranking axis)."""
        strat = DeepOversoldStrategy()
        df_shallow = _frame(_falling_then_floor(n_fall=18, floor_len=0), volume=10_000_000)
        df_deep = _frame(_falling_then_floor(n_fall=45, floor_len=0), volume=10_000_000)
        r_shallow = strat._evaluate(trader, df_shallow, regime_status="Bearish")
        r_deep = strat._evaluate(trader, df_deep, regime_status="Bearish")
        assert r_shallow is not None and r_deep is not None
        assert r_deep.components["oversold_age"] >= r_shallow.components["oversold_age"]
        assert r_deep.score >= r_shallow.score

    def test_too_few_bars_returns_none(self, trader):
        strat = DeepOversoldStrategy()
        df = _frame([100.0, 99.0, 98.0], volume=10_000_000)
        assert strat._evaluate(trader, df, regime_status="Neutral") is None

    def test_solvency_filter_drops_known_distress(self, trader):
        trader.config = _config(solvency=True)
        strat = DeepOversoldStrategy()
        df = _frame(_falling_then_floor(n_fall=40, floor_len=0), volume=10_000_000)

        res = strat.process(
            trader, df, "DISTRESS", dict(df.iloc[-1]),
            _ctx(solvency={"DISTRESS": C.DEEP_OVERSOLD_Z_DISTRESS - 0.01}),
        )

        assert res is None

    def test_solvency_filter_keeps_unknown_z(self, trader):
        trader.config = _config(solvency=True)
        strat = DeepOversoldStrategy()
        df = _frame(_falling_then_floor(n_fall=40, floor_len=0), volume=10_000_000)

        res = strat.process(trader, df, "UNKNOWN", dict(df.iloc[-1]), _ctx(solvency={}))

        assert res is not None

    def test_ha_solvency_filter_is_noop(self):
        strat = DeepOversoldHAStrategy()

        assert strat._solvency_ok("DISTRESS", {"DISTRESS": C.DEEP_OVERSOLD_Z_DISTRESS - 0.01})

    @pytest.mark.parametrize("benchmark_df", [None, _spy_frame(bull=True)])
    def test_nonbull_gate_fails_closed_on_missing_or_bull_spy(self, trader, benchmark_df):
        trader.config = _config(nonbull=True)
        strat = DeepOversoldStrategy()
        df = _frame(_falling_then_floor(n_fall=40, floor_len=0), volume=10_000_000)

        res = strat.process(
            trader, df, "AAPL", dict(df.iloc[-1]),
            _ctx(benchmark_df=benchmark_df),
        )

        assert res is None

    def test_nonbull_gate_fires_on_nonbull_spy(self, trader):
        trader.config = _config(nonbull=True)
        strat = DeepOversoldStrategy()
        df = _frame(_falling_then_floor(n_fall=40, floor_len=0), volume=10_000_000)

        res = strat.process(
            trader, df, "AAPL", dict(df.iloc[-1]),
            _ctx(benchmark_df=_spy_frame(bull=False)),
        )

        assert res is not None
