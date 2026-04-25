"""Tests for the Phase 3.2 null-strategy baselines."""

# pylint: disable=missing-function-docstring

from __future__ import annotations

import pickle
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from bh_ftmo.backtest.baselines import (
    MondayInFridayOutStrategy,
    RandomEntryAtrExitStrategy,
    SimpleRsi14Strategy,
)
from bh_ftmo.backtest.calendar_provider import NullCalendarProvider
from bh_ftmo.backtest.engine import run_challenge
from bh_ftmo.backtest.swap import SwapRates
from bh_ftmo.backtest.types import PairSpec

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

BASE_CONFIG = {
    "initial_balance": 100_000.0,
    "account_currency": "USD",
    "phase": "challenge",
    "profit_target_pct": 0.50,
    "daily_loss_pct": 0.10,
    "max_loss_pct": 0.20,
    "max_loss_type": "static",
    "min_trading_days": 1,
    "max_trading_days": 14,
    "server_timezone": "Europe/Prague",
    "commission_per_lot_round_turn": 0.0,
    "swap_model": "standard",
}

PAIR_SPECS = {
    "EUR_USD": PairSpec("EUR_USD", 0.0001, 100_000),
    "GBP_USD": PairSpec("GBP_USD", 0.0001, 100_000),
    "AUD_USD": PairSpec("AUD_USD", 0.0001, 100_000),
    "NZD_USD": PairSpec("NZD_USD", 0.0001, 100_000),
    "USD_CHF": PairSpec("USD_CHF", 0.0001, 100_000),
}


def _bars_from_closes(
    closes: list[float],
    *,
    start_ts: datetime,
    spread: float = 0.0002,
    bar_hours: int = 4,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for idx, close_bid in enumerate(closes):
        ts = start_ts + timedelta(hours=bar_hours * idx)
        open_bid = closes[idx - 1] if idx > 0 else close_bid - 0.0005
        high_bid = max(open_bid, close_bid) + 0.0006
        low_bid = min(open_bid, close_bid) - 0.0006
        rows.append(
            {
                "timestamp": ts,
                "open_bid": open_bid,
                "open_ask": open_bid + spread,
                "close_bid": close_bid,
                "close_ask": close_bid + spread,
                "high_bid": high_bid,
                "high_ask": high_bid + spread,
                "low_bid": low_bid,
                "low_ask": low_bid + spread,
            }
        )
    return pd.DataFrame(rows)



def _flat_bars(
    *,
    start_ts: datetime,
    periods: int,
    base_price: float = 1.1000,
    spread: float = 0.0002,
    bar_hours: int = 4,
) -> pd.DataFrame:
    closes = [base_price for _ in range(periods)]
    return _bars_from_closes(closes, start_ts=start_ts, spread=spread, bar_hours=bar_hours)



def _bars_1h_from_4h(frame: pd.DataFrame, *, spike: float, spread: float = 0.0002) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for bar_row in frame.itertuples(index=False):
        open_bid = float(bar_row.open_bid)
        close_bid = float(bar_row.close_bid)
        for hour in range(1, 5):
            ts = pd.Timestamp(bar_row.timestamp).to_pydatetime() + timedelta(hours=hour)
            close_step = open_bid + ((close_bid - open_bid) * hour / 4.0)
            high_bid = max(open_bid, close_step) + spike
            low_bid = min(open_bid, close_step) - spike
            rows.append(
                {
                    "timestamp": ts,
                    "close_bid": close_step,
                    "close_ask": close_step + spread,
                    "high_bid": high_bid,
                    "high_ask": high_bid + spread,
                    "low_bid": low_bid,
                    "low_ask": low_bid + spread,
                }
            )
    return pd.DataFrame(rows)



def _utc_from_ny(year: int, month: int, day: int, hour: int) -> datetime:
    return datetime(year, month, day, hour, tzinfo=NY).astimezone(UTC).replace(tzinfo=None)



def _count_by_direction(signals):
    longs = sum(signal.direction == 1 for signal in signals)
    shorts = sum(signal.direction == -1 for signal in signals)
    return longs, shorts



def _generic_atr(frame: pd.DataFrame, value: float = 0.0015) -> pd.Series:
    return pd.Series(value, index=pd.to_datetime(frame["timestamp"]))



def _challenge_inputs_for_active_trading() -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], dict[str, pd.Series]]:
    start_ts = datetime(2026, 1, 5, 0, 0)
    timestamps = [start_ts + timedelta(hours=4 * idx) for idx in range(84)]
    closes = [1.1000 + (0.0040 if idx % 2 == 0 else -0.0040) for idx, _ in enumerate(timestamps)]
    frame = _bars_from_closes(closes, start_ts=start_ts)
    bars_4h = {"EUR_USD": frame}
    bars_1h = {"EUR_USD": _bars_1h_from_4h(frame, spike=0.0035)}
    atr = {"EUR_USD": _generic_atr(frame, value=0.0010)}
    return bars_4h, bars_1h, atr



def _challenge_inputs_for_monday_strategy() -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], dict[str, pd.Series]]:
    start_ts = datetime(2026, 1, 5, 2, 0)
    frame = _flat_bars(start_ts=start_ts, periods=84, base_price=1.1000)
    bars_4h = {"EUR_USD": frame}
    bars_1h = {"EUR_USD": _bars_1h_from_4h(frame, spike=0.0002)}
    atr = {"EUR_USD": _generic_atr(frame, value=0.0010)}
    return bars_4h, bars_1h, atr



def _run(strategy, bars_4h, bars_1h, atr_by_symbol, *, sizing_config: dict) -> object:
    signals = strategy.generate_signals(bars_4h)
    return run_challenge(
        bars_4h=bars_4h,
        bars_1h=bars_1h,
        signals=signals,
        atr_by_symbol=atr_by_symbol,
        pair_specs={symbol: PAIR_SPECS[symbol] for symbol in bars_4h},
        ftmo_config=dict(BASE_CONFIG),
        sizing_config=sizing_config,
        swap_rates_by_symbol={symbol: SwapRates(0.0, 0.0) for symbol in bars_4h},
        calendar_provider=NullCalendarProvider(),
        start_ts=min(frame["timestamp"].min() for frame in bars_4h.values()),
        start_equity=100_000.0,
        rng_seed=17,
    )



def test_random_baseline_seed_determinism():
    bars_4h = {"EUR_USD": _flat_bars(start_ts=datetime(2026, 1, 5, 0, 0), periods=500)}
    strategy = RandomEntryAtrExitStrategy(seed=7, symbols=["EUR_USD"], signal_density=0.2)
    assert strategy.generate_signals(bars_4h) == strategy.generate_signals(bars_4h)



def test_random_baseline_seed_divergence():
    bars_4h = {"EUR_USD": _flat_bars(start_ts=datetime(2026, 1, 5, 0, 0), periods=1000)}
    first = RandomEntryAtrExitStrategy(seed=7, symbols=["EUR_USD"], signal_density=0.2)
    second = RandomEntryAtrExitStrategy(seed=8, symbols=["EUR_USD"], signal_density=0.2)
    assert first.generate_signals(bars_4h) != second.generate_signals(bars_4h)



def test_random_baseline_density_matches_config():
    start_ts = datetime(2026, 1, 5, 0, 0)
    symbols = ["EUR_USD", "GBP_USD", "AUD_USD", "NZD_USD", "USD_CHF"]
    bars_4h = {
        symbol: _flat_bars(start_ts=start_ts, periods=10_000, base_price=1.05 + (idx * 0.01))
        for idx, symbol in enumerate(symbols)
    }
    strategy = RandomEntryAtrExitStrategy(seed=11, symbols=symbols, signal_density=0.05)
    signals = strategy.generate_signals(bars_4h)
    expected = 0.05 * 50_000
    assert len(signals) == pytest.approx(expected, rel=0.20)



def test_random_baseline_direction_is_balanced():
    bars_4h = {"EUR_USD": _flat_bars(start_ts=datetime(2026, 1, 5, 0, 0), periods=20_000)}
    strategy = RandomEntryAtrExitStrategy(seed=19, symbols=["EUR_USD"], signal_density=0.5)
    longs, shorts = _count_by_direction(strategy.generate_signals(bars_4h))
    imbalance = abs(longs - shorts) / (longs + shorts)
    assert imbalance <= 0.10



def test_random_baseline_picklable():
    bars_4h = {"EUR_USD": _flat_bars(start_ts=datetime(2026, 1, 5, 0, 0), periods=200)}
    strategy = RandomEntryAtrExitStrategy(seed=23, symbols=["EUR_USD"], signal_density=0.15)
    restored = pickle.loads(pickle.dumps(strategy))
    assert restored.generate_signals(bars_4h) == strategy.generate_signals(bars_4h)



def test_monday_friday_emits_one_signal_per_monday():
    bars_4h = {"EUR_USD": _flat_bars(start_ts=datetime(2026, 1, 5, 0, 0), periods=42 * 4)}
    strategy = MondayInFridayOutStrategy()
    signals = strategy.generate_signals(bars_4h)
    assert len(signals) == 4



def test_monday_friday_only_eur_usd_by_default():
    bars_4h = {
        "EUR_USD": _flat_bars(start_ts=datetime(2026, 1, 5, 0, 0), periods=60),
        "GBP_USD": _flat_bars(start_ts=datetime(2026, 1, 5, 0, 0), periods=60, base_price=1.2500),
    }
    strategy = MondayInFridayOutStrategy()
    assert {signal.symbol for signal in strategy.generate_signals(bars_4h)} == {"EUR_USD"}



def test_monday_friday_custom_symbol():
    bars_4h = {
        "GBP_USD": _flat_bars(start_ts=datetime(2026, 1, 5, 0, 0), periods=60, base_price=1.2500)
    }
    strategy = MondayInFridayOutStrategy(symbol="GBP_USD")
    assert {signal.symbol for signal in strategy.generate_signals(bars_4h)} == {"GBP_USD"}



def test_monday_friday_direction_always_long():
    bars_4h = {"EUR_USD": _flat_bars(start_ts=datetime(2026, 1, 5, 0, 0), periods=60)}
    strategy = MondayInFridayOutStrategy()
    assert {signal.direction for signal in strategy.generate_signals(bars_4h)} == {1}



def test_monday_friday_picklable():
    bars_4h = {"EUR_USD": _flat_bars(start_ts=datetime(2026, 1, 5, 0, 0), periods=60)}
    strategy = MondayInFridayOutStrategy()
    restored = pickle.loads(pickle.dumps(strategy))
    assert restored.generate_signals(bars_4h) == strategy.generate_signals(bars_4h)



def test_rsi_baseline_emits_long_when_oversold():
    closes = [1.2000 - (0.0020 * idx) for idx in range(40)]
    bars_4h = {"EUR_USD": _bars_from_closes(closes, start_ts=datetime(2026, 1, 5, 0, 0))}
    strategy = SimpleRsi14Strategy(symbols=["EUR_USD"])
    signals = strategy.generate_signals(bars_4h)
    assert signals
    assert any(signal.direction == 1 for signal in signals)



def test_rsi_baseline_emits_short_when_overbought():
    closes = [1.0000 + (0.0020 * idx) for idx in range(40)]
    bars_4h = {"EUR_USD": _bars_from_closes(closes, start_ts=datetime(2026, 1, 5, 0, 0))}
    strategy = SimpleRsi14Strategy(symbols=["EUR_USD"])
    signals = strategy.generate_signals(bars_4h)
    assert signals
    assert any(signal.direction == -1 for signal in signals)



def test_rsi_baseline_no_signal_when_neutral():
    closes = [1.1000 + (0.0010 if idx % 2 == 0 else -0.0010) for idx in range(60)]
    bars_4h = {"EUR_USD": _bars_from_closes(closes, start_ts=datetime(2026, 1, 5, 0, 0))}
    strategy = SimpleRsi14Strategy(symbols=["EUR_USD"])
    assert strategy.generate_signals(bars_4h) == []



def test_rsi_baseline_skips_warmup():
    closes = [1.2000 - (0.0020 * idx) for idx in range(40)]
    frame = _bars_from_closes(closes, start_ts=datetime(2026, 1, 5, 0, 0))
    strategy = SimpleRsi14Strategy(symbols=["EUR_USD"], rsi_window=14)
    signals = strategy.generate_signals({"EUR_USD": frame})
    warmup_cutoff = frame["timestamp"].iloc[14]
    assert signals
    assert min(signal.timestamp for signal in signals) >= warmup_cutoff



def test_rsi_baseline_picklable():
    closes = [1.2000 - (0.0020 * idx) for idx in range(40)]
    bars_4h = {"EUR_USD": _bars_from_closes(closes, start_ts=datetime(2026, 1, 5, 0, 0))}
    strategy = SimpleRsi14Strategy(symbols=["EUR_USD"])
    restored = pickle.loads(pickle.dumps(strategy))
    assert restored.generate_signals(bars_4h) == strategy.generate_signals(bars_4h)



def test_random_baseline_runs_through_engine_end_to_end():
    bars_4h, bars_1h, atr = _challenge_inputs_for_active_trading()
    strategy = RandomEntryAtrExitStrategy(seed=29, symbols=["EUR_USD"], signal_density=0.35)
    result = _run(
        strategy,
        bars_4h,
        bars_1h,
        atr,
        sizing_config={"risk_pct_per_trade": 0.003, "k_stop": 1.0, "k_target": 1.0},
    )
    assert len(result.trades) > 0
    assert result.outcome in {"passed", "failed", "push", "in_progress"}



def test_monday_friday_baseline_runs_through_engine_end_to_end():
    bars_4h, bars_1h, atr = _challenge_inputs_for_monday_strategy()
    strategy = MondayInFridayOutStrategy()
    result = _run(
        strategy,
        bars_4h,
        bars_1h,
        atr,
        sizing_config={
            "risk_pct_per_trade": 0.003,
            "k_stop": 100.0,
            "k_target": 100.0,
            "weekend_flatten_hours_before_close": 4,
        },
    )
    assert len(result.trades) > 0
    weekend_flatten_count = sum(trade.exit_reason == "weekend_flatten" for trade in result.trades)
    assert weekend_flatten_count >= max(1, len(result.trades) // 2)



def test_rsi_baseline_runs_through_engine_end_to_end():
    bars_4h, bars_1h, atr = _challenge_inputs_for_active_trading()
    strategy = SimpleRsi14Strategy(symbols=["EUR_USD"], oversold=45.0, overbought=55.0)
    result = _run(
        strategy,
        bars_4h,
        bars_1h,
        atr,
        sizing_config={"risk_pct_per_trade": 0.003, "k_stop": 1.0, "k_target": 1.0},
    )
    assert len(result.trades) > 0
    assert all(trade.stop > 0 and trade.target > 0 for trade in result.trades)
    assert any(
        (trade.direction > 0 and trade.stop < trade.open_price < trade.target)
        or (trade.direction < 0 and trade.target < trade.open_price < trade.stop)
        for trade in result.trades
    )
