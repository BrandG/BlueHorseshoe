"""Integration tests for the FTMO backtest engine."""

from __future__ import annotations

# pylint: disable=missing-function-docstring,too-many-lines,unused-variable,duplicate-code

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from bh_ftmo.analysis.strategy import Signal
from bh_ftmo.backtest.calendar_provider import NullCalendarProvider
from bh_ftmo.backtest.engine import StartConfig, run_challenge, run_n_randomized
from bh_ftmo.backtest.swap import SwapRates
from bh_ftmo.backtest.types import PairSpec

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


BASE_CONFIG = {
    "initial_balance": 100_000.0,
    "account_currency": "USD",
    "phase": "challenge",
    "profit_target_pct": 0.10,
    "daily_loss_pct": 0.05,
    "max_loss_pct": 0.10,
    "max_loss_type": "static",
    "min_trading_days": 1,
    "max_trading_days": 14,
    "server_timezone": "Europe/Prague",
    "commission_per_lot_round_turn": 0.0,
    "swap_model": "standard",
}


PAIR_SPECS = {
    "EUR_USD": PairSpec("EUR_USD", 0.0001, 100_000),
    "USD_JPY": PairSpec("USD_JPY", 0.01, 100_000),
}



def _signal(symbol: str, ts: datetime, direction: int = 1) -> Signal:
    return Signal(
        symbol=symbol,
        strategy="baseline",
        timestamp=ts,
        direction=direction,
        score=1.0,
        components={"edge": 1.0},
        above_threshold=True,
    )



def _frame_4h(rows: list[tuple[datetime, float, float, float, float]]) -> pd.DataFrame:
    data = [
        {
            "timestamp": ts,
            "open_bid": open_bid,
            "open_ask": open_ask,
            "close_bid": close_bid,
            "close_ask": close_ask,
            "high_bid": max(open_bid, close_bid),
            "high_ask": max(open_ask, close_ask),
            "low_bid": min(open_bid, close_bid),
            "low_ask": min(open_ask, close_ask),
        }
        for ts, open_bid, open_ask, close_bid, close_ask in rows
    ]
    frame = pd.DataFrame(data)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    return frame



def _frame_1h(rows: list[tuple[datetime, float, float, float, float]]) -> pd.DataFrame:
    data = [
        {
            "timestamp": ts,
            "close_bid": close_bid,
            "close_ask": close_ask,
            "high_bid": high_bid,
            "high_ask": high_bid + 0.0002,
            "low_bid": low_bid,
            "low_ask": low_bid + 0.0002,
        }
        for ts, close_bid, close_ask, high_bid, low_bid in rows
    ]
    frame = pd.DataFrame(data)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    frame["high_ask"] = frame["high_bid"] + 0.0002
    frame["low_ask"] = frame["low_bid"] + 0.0002
    return frame



def _frame_1h_jpy(rows: list[tuple[datetime, float, float, float, float]]) -> pd.DataFrame:
    data = [
        {
            "timestamp": ts,
            "close_bid": close_bid,
            "close_ask": close_ask,
            "high_bid": high_bid,
            "high_ask": high_bid + 0.02,
            "low_bid": low_bid,
            "low_ask": low_bid + 0.02,
        }
        for ts, close_bid, close_ask, high_bid, low_bid in rows
    ]
    frame = pd.DataFrame(data)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    return frame



def _pass_fixture():
    t0 = datetime(2026, 1, 12, 10, 0)
    t1 = t0 + timedelta(hours=4)
    t2 = t1 + timedelta(hours=4)
    bars_4h = {
        "EUR_USD": _frame_4h(
            [
                (t0, 1.0998, 1.1000, 1.1002, 1.1004),
                (t1, 1.0998, 1.1000, 1.1100, 1.1102),
                (t2, 1.1100, 1.1102, 1.1100, 1.1102),
            ]
        )
    }
    bars_1h = {
        "EUR_USD": _frame_1h(
            [
                (t1 + timedelta(hours=1), 1.1100, 1.1102, 1.1110, 1.0990),
                (t1 + timedelta(hours=2), 1.1100, 1.1102, 1.1105, 1.1095),
                (t1 + timedelta(hours=3), 1.1100, 1.1102, 1.1105, 1.1095),
                (t1 + timedelta(hours=4), 1.1100, 1.1102, 1.1105, 1.1095),
            ]
        )
    }
    atr = {"EUR_USD": pd.Series([0.0040, 0.0040, 0.0040], index=[t0, t1, t2])}
    config = dict(BASE_CONFIG)
    config["profit_target_pct"] = 0.01
    sizing = {"risk_pct_per_trade": 0.006, "k_stop": 1.5, "k_target": 2.5}
    return bars_4h, bars_1h, atr, config, sizing, [_signal("EUR_USD", t0)]



def _daily_loss_fixture():
    bars_4h, bars_1h, atr, config, sizing, signals = _pass_fixture()
    t1 = signals[0].timestamp + timedelta(hours=4)
    bars_4h["EUR_USD"] = _frame_4h(
        [
            (signals[0].timestamp, 1.0998, 1.1000, 1.1002, 1.1004),
            (t1, 1.0998, 1.1000, 1.0940, 1.0942),
            (t1 + timedelta(hours=4), 1.0940, 1.0942, 1.0940, 1.0942),
        ]
    )
    bars_1h["EUR_USD"] = _frame_1h(
        [
            (t1 + timedelta(hours=1), 1.0940, 1.0942, 1.1005, 1.0935),
            (t1 + timedelta(hours=2), 1.0940, 1.0942, 1.0945, 1.0938),
            (t1 + timedelta(hours=3), 1.0940, 1.0942, 1.0945, 1.0938),
            (t1 + timedelta(hours=4), 1.0940, 1.0942, 1.0945, 1.0938),
        ]
    )
    config = dict(config)
    config["profit_target_pct"] = 0.50
    config["daily_loss_pct"] = 0.003
    config["max_loss_pct"] = 0.20
    return bars_4h, bars_1h, atr, config, sizing, signals



def test_run_challenge_single_trade_passes_with_expected_ledger():
    bars_4h, bars_1h, atr, config, sizing, signals = _pass_fixture()
    result = run_challenge(
        bars_4h=bars_4h,
        bars_1h=bars_1h,
        signals=signals,
        atr_by_symbol=atr,
        pair_specs={"EUR_USD": PAIR_SPECS["EUR_USD"]},
        ftmo_config=config,
        sizing_config=sizing,
        swap_rates_by_symbol={"EUR_USD": SwapRates(0.0, 0.0)},
        calendar_provider=NullCalendarProvider(),
        start_ts=signals[0].timestamp,
        start_equity=100_000.0,
        rng_seed=7,
    )
    assert result.outcome == "passed"
    assert result.failed_by is None
    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == "target"
    assert result.trades[0].risk_at_open_account_ccy == pytest.approx(600.0)
    assert result.final_equity_account_ccy == pytest.approx(101_000.0)



def test_run_challenge_fails_by_daily_loss_with_expected_equity():
    bars_4h, bars_1h, atr, config, sizing, signals = _daily_loss_fixture()
    result = run_challenge(
        bars_4h=bars_4h,
        bars_1h=bars_1h,
        signals=signals,
        atr_by_symbol=atr,
        pair_specs={"EUR_USD": PAIR_SPECS["EUR_USD"]},
        ftmo_config=config,
        sizing_config=sizing,
        swap_rates_by_symbol={"EUR_USD": SwapRates(0.0, 0.0)},
        calendar_provider=NullCalendarProvider(),
        start_ts=signals[0].timestamp,
        start_equity=100_000.0,
        rng_seed=8,
    )
    assert result.outcome == "failed"
    assert result.failed_by == "daily_loss"
    assert result.final_equity_account_ccy == pytest.approx(99_400.0)


def _overlay_daily_fail_fixture():
    t0 = datetime(2026, 1, 12, 10, 0)
    t1 = t0 + timedelta(hours=4)
    t2 = t1 + timedelta(hours=4)
    t3 = t2 + timedelta(hours=4)
    bars_4h = {
        "EUR_USD": _frame_4h(
            [
                (t0, 1.0998, 1.1000, 1.1000, 1.1002),
                (t1, 1.0998, 1.1000, 1.0760, 1.0762),
                (t2, 1.0760, 1.0762, 1.0550, 1.0552),
                (t3, 1.0550, 1.0552, 1.0550, 1.0552),
            ]
        )
    }
    bars_4h["EUR_USD"].loc[1, "low_bid"] = 1.0600
    bars_4h["EUR_USD"].loc[1, "low_ask"] = 1.0602
    bars_1h = {
        "EUR_USD": _frame_1h(
            [
                (t1 + timedelta(hours=1), 1.0950, 1.0952, 1.1005, 1.0900),
                (t1 + timedelta(hours=2), 1.0850, 1.0852, 1.0900, 1.0800),
                (t1 + timedelta(hours=3), 1.0800, 1.0802, 1.0850, 1.0750),
                (t1 + timedelta(hours=4), 1.0760, 1.0762, 1.0800, 1.0600),
                (t2 + timedelta(hours=1), 1.0700, 1.0702, 1.0760, 1.0680),
                (t2 + timedelta(hours=2), 1.0650, 1.0652, 1.0700, 1.0630),
                (t2 + timedelta(hours=3), 1.0600, 1.0602, 1.0650, 1.0580),
                (t2 + timedelta(hours=4), 1.0550, 1.0552, 1.0600, 1.0550),
            ]
        )
    }
    atr = {"EUR_USD": pd.Series([0.0040, 0.0040, 0.0040, 0.0040], index=[t0, t1, t2, t3])}
    config = dict(BASE_CONFIG)
    config["profit_target_pct"] = 0.50
    sizing = {"risk_pct_per_trade": 0.50, "k_stop": 100.0, "k_target": 250.0}
    return bars_4h, bars_1h, atr, config, sizing, [_signal("EUR_USD", t0)]


def test_run_challenge_with_overlay_enabled_reduces_daily_fails() -> None:
    bars_4h, bars_1h, atr, config, sizing, signals = _overlay_daily_fail_fixture()
    no_overlay = run_challenge(
        bars_4h=bars_4h,
        bars_1h=bars_1h,
        signals=signals,
        atr_by_symbol=atr,
        pair_specs={"EUR_USD": PAIR_SPECS["EUR_USD"]},
        ftmo_config=config,
        sizing_config=sizing,
        swap_rates_by_symbol={"EUR_USD": SwapRates(0.0, 0.0)},
        calendar_provider=NullCalendarProvider(),
        start_ts=signals[0].timestamp,
        start_equity=100_000.0,
        rng_seed=18,
    )
    with_overlay = run_challenge(
        bars_4h=bars_4h,
        bars_1h=bars_1h,
        signals=signals,
        atr_by_symbol=atr,
        pair_specs={"EUR_USD": PAIR_SPECS["EUR_USD"]},
        ftmo_config=config,
        sizing_config=sizing,
        swap_rates_by_symbol={"EUR_USD": SwapRates(0.0, 0.0)},
        calendar_provider=NullCalendarProvider(),
        start_ts=signals[0].timestamp,
        start_equity=100_000.0,
        rng_seed=18,
        risk_overlay_config={"baseline": {"enabled": True, "buffer_mult": 10.0, "soft_daily_limit": -0.04}},
    )

    assert no_overlay.failed_by == "daily_loss"
    assert with_overlay.failed_by != "daily_loss"
    assert with_overlay.n_liquidations >= 1


def test_run_challenge_overlay_disabled_unchanged() -> None:
    bars_4h, bars_1h, atr, config, sizing, signals = _overlay_daily_fail_fixture()
    no_overlay = run_challenge(
        bars_4h=bars_4h,
        bars_1h=bars_1h,
        signals=signals,
        atr_by_symbol=atr,
        pair_specs={"EUR_USD": PAIR_SPECS["EUR_USD"]},
        ftmo_config=config,
        sizing_config=sizing,
        swap_rates_by_symbol={"EUR_USD": SwapRates(0.0, 0.0)},
        calendar_provider=NullCalendarProvider(),
        start_ts=signals[0].timestamp,
        start_equity=100_000.0,
        rng_seed=19,
    )
    disabled = run_challenge(
        bars_4h=bars_4h,
        bars_1h=bars_1h,
        signals=signals,
        atr_by_symbol=atr,
        pair_specs={"EUR_USD": PAIR_SPECS["EUR_USD"]},
        ftmo_config=config,
        sizing_config=sizing,
        swap_rates_by_symbol={"EUR_USD": SwapRates(0.0, 0.0)},
        calendar_provider=NullCalendarProvider(),
        start_ts=signals[0].timestamp,
        start_equity=100_000.0,
        rng_seed=19,
        risk_overlay_config={"baseline": {"enabled": False}},
    )

    assert disabled.outcome == no_overlay.outcome
    assert disabled.failed_by == no_overlay.failed_by
    assert disabled.final_equity_account_ccy == pytest.approx(no_overlay.final_equity_account_ccy)
    assert disabled.trades == no_overlay.trades
    assert disabled.breaches == no_overlay.breaches
    assert disabled.n_blocked_entries == no_overlay.n_blocked_entries == 0
    assert disabled.n_liquidations == no_overlay.n_liquidations == 0



def test_run_challenge_reasserts_invalid_max_loss_type():
    bars_4h, bars_1h, atr, config, sizing, signals = _pass_fixture()
    config = dict(config)
    config["max_loss_type"] = "PLACEHOLDER"
    with pytest.raises(AssertionError, match="max_loss_type"):
        run_challenge(
            bars_4h=bars_4h,
            bars_1h=bars_1h,
            signals=signals,
            atr_by_symbol=atr,
            pair_specs={"EUR_USD": PAIR_SPECS["EUR_USD"]},
            ftmo_config=config,
            sizing_config=sizing,
            swap_rates_by_symbol={"EUR_USD": SwapRates(0.0, 0.0)},
            calendar_provider=NullCalendarProvider(),
            start_ts=signals[0].timestamp,
            start_equity=100_000.0,
            rng_seed=9,
        )



def test_run_challenge_refuses_to_open_after_breach():
    bars_4h, bars_1h, atr, config, sizing, signals = _daily_loss_fixture()
    later_signal_ts = signals[0].timestamp + timedelta(hours=8)
    result = run_challenge(
        bars_4h=bars_4h,
        bars_1h=bars_1h,
        signals=signals + [_signal("EUR_USD", later_signal_ts)],
        atr_by_symbol={
            "EUR_USD": pd.Series(
                [0.0040, 0.0040, 0.0040],
                index=[signals[0].timestamp, signals[0].timestamp + timedelta(hours=4), later_signal_ts],
            )
        },
        pair_specs={"EUR_USD": PAIR_SPECS["EUR_USD"]},
        ftmo_config=config,
        sizing_config=sizing,
        swap_rates_by_symbol={"EUR_USD": SwapRates(0.0, 0.0)},
        calendar_provider=NullCalendarProvider(),
        start_ts=signals[0].timestamp,
        start_equity=100_000.0,
        rng_seed=10,
    )
    assert any(reason == "rule_blocked" for _, reason in result.skipped_signals)



def test_run_challenge_refuses_to_open_after_target_lock():
    bars_4h, bars_1h, atr, config, sizing, signals = _pass_fixture()
    later_signal_ts = signals[0].timestamp + timedelta(hours=8)
    atr["EUR_USD"] = pd.Series([0.0040, 0.0040, 0.0040], index=[signals[0].timestamp, signals[0].timestamp + timedelta(hours=4), later_signal_ts])
    result = run_challenge(
        bars_4h=bars_4h,
        bars_1h=bars_1h,
        signals=signals + [_signal("EUR_USD", later_signal_ts)],
        atr_by_symbol=atr,
        pair_specs={"EUR_USD": PAIR_SPECS["EUR_USD"]},
        ftmo_config=config,
        sizing_config=sizing,
        swap_rates_by_symbol={"EUR_USD": SwapRates(0.0, 0.0)},
        calendar_provider=NullCalendarProvider(),
        start_ts=signals[0].timestamp,
        start_equity=100_000.0,
        rng_seed=11,
    )
    assert any(reason == "target_already_passed" for _, reason in result.skipped_signals)



def test_portfolio_event_ordering_halts_on_first_breach_and_flushes_other_position():
    t0 = datetime(2026, 1, 12, 10, 0)
    t1 = t0 + timedelta(hours=4)
    t2 = t1 + timedelta(hours=4)
    bars_4h = {
        "EUR_USD": _frame_4h(
            [
                (t0, 1.0998, 1.1000, 1.1000, 1.1002),
                (t1, 1.0998, 1.1000, 1.1200, 1.1202),
                (t2, 1.1200, 1.1202, 1.1200, 1.1202),
            ]
        ),
        "USD_JPY": _frame_4h(
            [
                (t0, 149.98, 150.00, 150.00, 150.02),
                (t1, 149.98, 150.00, 149.00, 149.02),
                (t2, 149.00, 149.02, 149.00, 149.02),
            ]
        ),
    }
    bars_1h = {
        "EUR_USD": _frame_1h(
            [
                (t1 + timedelta(hours=1), 1.1000, 1.1002, 1.1005, 1.0995),
                (t1 + timedelta(hours=2), 1.1200, 1.1202, 1.1210, 1.1035),
                (t1 + timedelta(hours=3), 1.1200, 1.1202, 1.1205, 1.1195),
                (t1 + timedelta(hours=4), 1.1200, 1.1202, 1.1205, 1.1195),
            ]
        ),
        "USD_JPY": _frame_1h_jpy(
            [
                (t1 + timedelta(hours=1), 149.00, 149.02, 150.05, 148.95),
                (t1 + timedelta(hours=2), 149.00, 149.02, 149.05, 148.95),
                (t1 + timedelta(hours=3), 149.00, 149.02, 149.05, 148.95),
                (t1 + timedelta(hours=4), 149.00, 149.02, 149.05, 148.95),
            ]
        ),
    }
    atr = {
        "EUR_USD": pd.Series([0.0040, 0.0040, 0.0040], index=[t0, t1, t2]),
        "USD_JPY": pd.Series([0.3000, 0.3000, 0.3000], index=[t0, t1, t2]),
    }
    config = dict(BASE_CONFIG)
    config["daily_loss_pct"] = 0.003
    config["max_loss_pct"] = 0.20
    config["profit_target_pct"] = 0.50
    sizing = {"risk_pct_per_trade": 0.006, "k_stop": 1.5, "k_target": 2.5, "max_concurrent_positions": 5}
    result = run_challenge(
        bars_4h=bars_4h,
        bars_1h=bars_1h,
        signals=[_signal("EUR_USD", t0), _signal("USD_JPY", t0)],
        atr_by_symbol=atr,
        pair_specs=PAIR_SPECS,
        ftmo_config=config,
        sizing_config=sizing,
        swap_rates_by_symbol={"EUR_USD": SwapRates(0.0, 0.0), "USD_JPY": SwapRates(0.0, 0.0)},
        calendar_provider=NullCalendarProvider(),
        start_ts=t0,
        start_equity=100_000.0,
        rng_seed=12,
    )
    assert result.outcome == "failed"
    assert result.failed_by == "daily_loss"
    assert len(result.trades) == 2
    assert result.trades[0].symbol == "USD_JPY"
    assert result.trades[0].exit_reason == "stop"
    assert result.trades[1].symbol == "EUR_USD"
    assert result.trades[1].exit_reason == "ftmo_breach"
    assert result.trades[1].close_ts == t1 + timedelta(hours=1)



def test_static_and_trailing_match_when_equity_never_rises():
    bars_4h, bars_1h, atr, config, sizing, signals = _daily_loss_fixture()
    static_result = run_challenge(
        bars_4h=bars_4h,
        bars_1h=bars_1h,
        signals=signals,
        atr_by_symbol=atr,
        pair_specs={"EUR_USD": PAIR_SPECS["EUR_USD"]},
        ftmo_config=dict(config, max_loss_type="static"),
        sizing_config=sizing,
        swap_rates_by_symbol={"EUR_USD": SwapRates(0.0, 0.0)},
        calendar_provider=NullCalendarProvider(),
        start_ts=signals[0].timestamp,
        start_equity=100_000.0,
        rng_seed=13,
    )
    trailing_result = run_challenge(
        bars_4h=bars_4h,
        bars_1h=bars_1h,
        signals=signals,
        atr_by_symbol=atr,
        pair_specs={"EUR_USD": PAIR_SPECS["EUR_USD"]},
        ftmo_config=dict(config, max_loss_type="trailing"),
        sizing_config=sizing,
        swap_rates_by_symbol={"EUR_USD": SwapRates(0.0, 0.0)},
        calendar_provider=NullCalendarProvider(),
        start_ts=signals[0].timestamp,
        start_equity=100_000.0,
        rng_seed=13,
    )
    assert static_result.outcome == trailing_result.outcome
    assert static_result.failed_by == trailing_result.failed_by
    assert static_result.final_equity_account_ccy == pytest.approx(trailing_result.final_equity_account_ccy)



def test_static_and_trailing_diverge_on_rise_then_fall():
    t0 = datetime(2026, 1, 12, 10, 0)
    t1 = t0 + timedelta(hours=4)
    t2 = t1 + timedelta(hours=4)
    t3 = t2 + timedelta(hours=4)
    bars_4h = {
        "EUR_USD": _frame_4h(
            [
                (t0, 1.0998, 1.1000, 1.1000, 1.1002),
                (t1, 1.0998, 1.1000, 1.1050, 1.1052),
                (t2, 1.1050, 1.1052, 1.0970, 1.0972),
                (t3, 1.0970, 1.0972, 1.0970, 1.0972),
            ]
        )
    }
    bars_1h = {
        "EUR_USD": _frame_1h(
            [
                (t1 + timedelta(hours=1), 1.1020, 1.1022, 1.1025, 1.1015),
                (t1 + timedelta(hours=2), 1.1035, 1.1037, 1.1040, 1.1030),
                (t1 + timedelta(hours=3), 1.1045, 1.1047, 1.1049, 1.1040),
                (t1 + timedelta(hours=4), 1.1050, 1.1052, 1.1050, 1.1045),
                (t2 + timedelta(hours=1), 1.1000, 1.1002, 1.1005, 1.0995),
                (t2 + timedelta(hours=2), 1.0985, 1.0987, 1.0990, 1.0980),
                (t2 + timedelta(hours=3), 1.0975, 1.0977, 1.0980, 1.0970),
                (t2 + timedelta(hours=4), 1.0970, 1.0972, 1.0975, 1.0968),
            ]
        )
    }
    atr = {"EUR_USD": pd.Series([0.0040, 0.0040, 0.0040, 0.0040], index=[t0, t1, t2, t3])}
    config = dict(BASE_CONFIG)
    config["max_loss_pct"] = 0.05
    config["daily_loss_pct"] = 0.20
    config["profit_target_pct"] = 0.50
    sizing = {"risk_pct_per_trade": 0.06, "k_stop": 1.5, "k_target": 100.0}

    static_result = run_challenge(
        bars_4h=bars_4h,
        bars_1h=bars_1h,
        signals=[_signal("EUR_USD", t0)],
        atr_by_symbol=atr,
        pair_specs={"EUR_USD": PAIR_SPECS["EUR_USD"]},
        ftmo_config=dict(config, max_loss_type="static"),
        sizing_config=sizing,
        swap_rates_by_symbol={"EUR_USD": SwapRates(0.0, 0.0)},
        calendar_provider=NullCalendarProvider(),
        start_ts=t0,
        start_equity=100_000.0,
        rng_seed=14,
    )
    trailing_result = run_challenge(
        bars_4h=bars_4h,
        bars_1h=bars_1h,
        signals=[_signal("EUR_USD", t0)],
        atr_by_symbol=atr,
        pair_specs={"EUR_USD": PAIR_SPECS["EUR_USD"]},
        ftmo_config=dict(config, max_loss_type="trailing"),
        sizing_config=sizing,
        swap_rates_by_symbol={"EUR_USD": SwapRates(0.0, 0.0)},
        calendar_provider=NullCalendarProvider(),
        start_ts=t0,
        start_equity=100_000.0,
        rng_seed=14,
    )
    assert static_result.failed_by is None
    assert trailing_result.failed_by == "max_loss"



def test_run_n_randomized_is_deterministic_across_worker_counts():
    bars_4h, bars_1h, atr, config, sizing, signals = _pass_fixture()
    starts = [
        StartConfig(start_ts=signals[0].timestamp, end_ts=signals[0].timestamp + timedelta(days=2), rng_seed=seed)
        for seed in range(4)
    ]
    serial = run_n_randomized(
        bars_4h=bars_4h,
        bars_1h=bars_1h,
        signals=signals,
        atr_by_symbol=atr,
        pair_specs={"EUR_USD": PAIR_SPECS["EUR_USD"]},
        ftmo_config=config,
        sizing_config=sizing,
        swap_rates_by_symbol={"EUR_USD": SwapRates(0.0, 0.0)},
        calendar_provider=NullCalendarProvider(),
        starts=starts,
        max_workers=1,
    )
    parallel = run_n_randomized(
        bars_4h=bars_4h,
        bars_1h=bars_1h,
        signals=signals,
        atr_by_symbol=atr,
        pair_specs={"EUR_USD": PAIR_SPECS["EUR_USD"]},
        ftmo_config=config,
        sizing_config=sizing,
        swap_rates_by_symbol={"EUR_USD": SwapRates(0.0, 0.0)},
        calendar_provider=NullCalendarProvider(),
        starts=starts,
        max_workers=2,
    )
    serial_projection = [(result.rng_seed, result.outcome, result.final_equity_account_ccy, tuple(result.trades)) for result in serial]
    parallel_projection = [(result.rng_seed, result.outcome, result.final_equity_account_ccy, tuple(result.trades)) for result in parallel]
    assert serial_projection == parallel_projection



def _utc_from_ny(year: int, month: int, day: int, hour: int) -> datetime:
    return datetime(year, month, day, hour, tzinfo=NY).astimezone(UTC).replace(tzinfo=None)



def test_weekend_flatten_closes_position_on_friday_window():
    t0 = _utc_from_ny(2026, 4, 23, 9)
    t1 = _utc_from_ny(2026, 4, 23, 13)
    t2 = _utc_from_ny(2026, 4, 24, 13)
    bars_4h = {
        "EUR_USD": _frame_4h(
            [
                (t0, 1.0998, 1.1000, 1.1000, 1.1002),
                (t1, 1.1000, 1.1002, 1.1010, 1.1012),
                (t2, 1.1010, 1.1012, 1.1010, 1.1012),
            ]
        )
    }
    bars_1h = {
        "EUR_USD": _frame_1h(
            [
                (t1 + timedelta(hours=1), 1.1005, 1.1007, 1.1007, 1.1001),
                (t1 + timedelta(hours=2), 1.1008, 1.1010, 1.1010, 1.1005),
                (t1 + timedelta(hours=3), 1.1009, 1.1011, 1.1011, 1.1006),
                (t1 + timedelta(hours=4), 1.1010, 1.1012, 1.1012, 1.1008),
                (t2 + timedelta(hours=1), 1.1010, 1.1012, 1.1012, 1.1008),
                (t2 + timedelta(hours=2), 1.1010, 1.1012, 1.1012, 1.1008),
                (t2 + timedelta(hours=3), 1.1010, 1.1012, 1.1012, 1.1008),
                (t2 + timedelta(hours=4), 1.1010, 1.1012, 1.1012, 1.1008),
            ]
        )
    }
    atr = {"EUR_USD": pd.Series([0.0040, 0.0040, 0.0040], index=[t0, t1, t2])}
    config = dict(BASE_CONFIG)
    config["profit_target_pct"] = 0.50
    sizing = {"risk_pct_per_trade": 0.006, "k_stop": 100.0, "k_target": 100.0, "weekend_flatten_hours_before_close": 4}
    result = run_challenge(
        bars_4h=bars_4h,
        bars_1h=bars_1h,
        signals=[_signal("EUR_USD", t0)],
        atr_by_symbol=atr,
        pair_specs={"EUR_USD": PAIR_SPECS["EUR_USD"]},
        ftmo_config=config,
        sizing_config=sizing,
        swap_rates_by_symbol={"EUR_USD": SwapRates(0.0, 0.0)},
        calendar_provider=NullCalendarProvider(),
        start_ts=t0,
        start_equity=100_000.0,
        rng_seed=15,
    )
    assert any(trade.exit_reason == "weekend_flatten" for trade in result.trades)


def test_swap_is_applied_before_new_daily_baseline_capture():
    t0 = datetime(2026, 1, 12, 18, 0)
    t1 = t0 + timedelta(hours=4)
    t2 = t1 + timedelta(hours=4)
    bars_4h = {
        "EUR_USD": _frame_4h(
            [
                (t0, 1.0998, 1.1000, 1.1000, 1.1002),
                (t1, 1.0998, 1.1000, 1.0955, 1.0957),
                (t2, 1.0955, 1.0957, 1.0955, 1.0957),
            ]
        )
    }
    bars_1h = {
        "EUR_USD": _frame_1h(
            [
                (datetime(2026, 1, 12, 23, 0), 1.0998, 1.1000, 1.1000, 1.0995),
                (datetime(2026, 1, 13, 0, 0), 1.0985, 1.0987, 1.0990, 1.0980),
                (datetime(2026, 1, 13, 1, 0), 1.0970, 1.0972, 1.0975, 1.0965),
                (datetime(2026, 1, 13, 2, 0), 1.0955, 1.0957, 1.0960, 1.0950),
            ]
        )
    }
    atr = {"EUR_USD": pd.Series([0.0040, 0.0040, 0.0040], index=[t0, t1, t2])}
    config = dict(BASE_CONFIG)
    config["daily_loss_pct"] = 0.05
    config["max_loss_pct"] = 0.20
    config["profit_target_pct"] = 0.50
    sizing = {"risk_pct_per_trade": 0.06, "k_stop": 1.5, "k_target": 100.0}
    result = run_challenge(
        bars_4h=bars_4h,
        bars_1h=bars_1h,
        signals=[_signal("EUR_USD", t0)],
        atr_by_symbol=atr,
        pair_specs={"EUR_USD": PAIR_SPECS["EUR_USD"]},
        ftmo_config=config,
        sizing_config=sizing,
        swap_rates_by_symbol={"EUR_USD": SwapRates(-100.0, -100.0)},
        calendar_provider=NullCalendarProvider(),
        start_ts=t0,
        start_equity=100_000.0,
        rng_seed=16,
    )
    assert result.outcome != "failed"
    assert result.equity_curve_daily.index[0] == datetime(2026, 1, 12, 23, 0)
    assert result.equity_curve_daily.iloc[0] == pytest.approx(98_800.0)



def test_deadline_blocks_new_entries_then_flattens_on_deadline_day():
    t0 = datetime(2026, 1, 12, 10, 0)
    t1 = t0 + timedelta(hours=4)
    t2 = datetime(2026, 1, 13, 10, 0)
    t3 = datetime(2026, 1, 15, 10, 0)
    bars_4h = {
        "EUR_USD": _frame_4h(
            [
                (t0, 1.0998, 1.1000, 1.1000, 1.1002),
                (t1, 1.1000, 1.1002, 1.1005, 1.1007),
                (t2, 1.1005, 1.1007, 1.1010, 1.1012),
                (t3, 1.1010, 1.1012, 1.1010, 1.1012),
            ]
        )
    }
    bars_1h = {
        "EUR_USD": _frame_1h(
            [
                (t1 + timedelta(hours=1), 1.1002, 1.1004, 1.1004, 1.0998),
                (t1 + timedelta(hours=2), 1.1003, 1.1005, 1.1005, 1.0999),
                (t1 + timedelta(hours=3), 1.1004, 1.1006, 1.1006, 1.1000),
                (t1 + timedelta(hours=4), 1.1005, 1.1007, 1.1007, 1.1001),
                (t2 + timedelta(hours=1), 1.1008, 1.1010, 1.1010, 1.1004),
                (t2 + timedelta(hours=2), 1.1009, 1.1011, 1.1011, 1.1005),
                (t2 + timedelta(hours=3), 1.1010, 1.1012, 1.1012, 1.1006),
                (t2 + timedelta(hours=4), 1.1010, 1.1012, 1.1012, 1.1007),
                (t3 + timedelta(hours=1), 1.1010, 1.1012, 1.1012, 1.1008),
                (t3 + timedelta(hours=2), 1.1010, 1.1012, 1.1012, 1.1008),
                (t3 + timedelta(hours=3), 1.1010, 1.1012, 1.1012, 1.1008),
                (t3 + timedelta(hours=4), 1.1010, 1.1012, 1.1012, 1.1008),
            ]
        )
    }
    atr = {"EUR_USD": pd.Series([0.0040, 0.0040, 0.0040, 0.0040], index=[t0, t1, t2, t3])}
    config = dict(BASE_CONFIG)
    config["profit_target_pct"] = 0.50
    sizing = {"risk_pct_per_trade": 0.006, "k_stop": 100.0, "k_target": 100.0}
    result = run_challenge(
        bars_4h=bars_4h,
        bars_1h=bars_1h,
        signals=[_signal("EUR_USD", t0), _signal("EUR_USD", t2)],
        atr_by_symbol=atr,
        pair_specs={"EUR_USD": PAIR_SPECS["EUR_USD"]},
        ftmo_config=config,
        sizing_config=sizing,
        swap_rates_by_symbol={"EUR_USD": SwapRates(0.0, 0.0)},
        calendar_provider=NullCalendarProvider(),
        start_ts=t0,
        start_equity=100_000.0,
        rng_seed=17,
        deadline=date(2026, 1, 15),
    )
    assert any(reason == "deadline_blocked" for _, reason in result.skipped_signals)
    assert any(trade.exit_reason == "deadline_flatten" for trade in result.trades)
