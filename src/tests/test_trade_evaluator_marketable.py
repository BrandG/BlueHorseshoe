import pandas as pd

from bluehorseshoe.analysis.trade_evaluator import TradeEvalConfig, evaluate_bars


CONFIG = TradeEvalConfig(hold_days=10, entry_style="marketable_next_open")


def make_bars(rows):
    return pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])


def evaluate(rows):
    return evaluate_bars(
        make_bars(rows),
        entry_price=100.0,
        stop_loss=98.0,
        take_profit=104.0,
        config=CONFIG,
    )


def quiet_bar(day, close=100.5):
    return (f"2026-01-{day:02d}", close, close + 1.0, close - 1.0, close, 1000)


def test_marketable_gap_down_fills_at_next_open():
    result = evaluate([
        ("2026-01-02", 101.0, 102.0, 99.0, 100.0, 1000),
        ("2026-01-03", 99.0, 101.0, 98.5, 100.0, 1000),
        ("2026-01-04", 100.0, 105.0, 99.5, 104.0, 1000),
    ])

    assert result["actual_entry"] == 99.0
    assert result["entry_date"] == "2026-01-03"
    assert result["outcome"] == "WIN"


def test_marketable_intraday_touch_fills_at_limit():
    result = evaluate([
        ("2026-01-02", 101.0, 102.0, 99.0, 100.0, 1000),
        ("2026-01-03", 101.0, 102.0, 99.5, 100.5, 1000),
        ("2026-01-04", 100.5, 105.0, 100.0, 104.0, 1000),
    ])

    assert result["actual_entry"] == 100.0
    assert result["entry_date"] == "2026-01-03"
    assert result["outcome"] == "WIN"


def test_marketable_no_fill_expires_after_next_session():
    result = evaluate([
        ("2026-01-02", 101.0, 102.0, 100.8, 101.5, 1000),
        ("2026-01-03", 101.0, 102.0, 100.5, 101.5, 1000),
        ("2026-01-04", 99.0, 105.0, 97.0, 104.0, 1000),
    ])

    assert result["outcome"] == "NOT_ENTERED"
    assert result["actual_entry"] is None


def test_marketable_does_not_look_ahead_to_signal_bar_low():
    result = evaluate([
        ("2026-01-02", 101.0, 102.0, 90.0, 100.0, 1000),
        ("2026-01-03", 99.0, 101.0, 98.5, 100.0, 1000),
        ("2026-01-04", 100.0, 105.0, 99.5, 104.0, 1000),
    ])

    assert result["actual_entry"] == 99.0
    assert result["entry_date"] == "2026-01-03"
    assert result["outcome"] == "WIN"


def test_marketable_post_fill_later_target_is_win():
    result = evaluate([
        ("2026-01-02", 101.0, 102.0, 100.8, 101.5, 1000),
        ("2026-01-03", 99.0, 101.0, 98.5, 100.0, 1000),
        ("2026-01-04", 100.0, 105.0, 99.5, 104.0, 1000),
    ])

    assert result["outcome"] == "WIN"
    assert result["exit_reason"] == "target"


def test_marketable_post_fill_later_stop_is_loss():
    result = evaluate([
        ("2026-01-02", 101.0, 102.0, 100.8, 101.5, 1000),
        ("2026-01-03", 99.0, 101.0, 98.5, 100.0, 1000),
        ("2026-01-04", 100.0, 101.0, 97.5, 98.0, 1000),
    ])

    assert result["outcome"] == "LOSS"
    assert result["exit_reason"] == "stop"


def test_marketable_timeout_counts_days_from_fill_bar():
    rows = [
        ("2026-01-02", 101.0, 102.0, 100.8, 101.5, 1000),
        ("2026-01-03", 99.0, 101.0, 98.5, 100.0, 1000),
    ]
    rows.extend(quiet_bar(day) for day in range(4, 14))

    result = evaluate(rows)

    assert result["outcome"] == "TIMEOUT"
    assert result["exit_reason"] == "time_exit"
    assert result["entry_date"] == "2026-01-03"
    assert result["days_held"] == 10
