"""Tests for the BH FTMO Phase 3 report renderer."""

from __future__ import annotations

# pylint: disable=missing-function-docstring,duplicate-code

from datetime import datetime, timedelta
import json
import re

import pandas as pd

from bh_ftmo.analysis.strategy import Signal
from bh_ftmo.backtest.calendar_provider import NullCalendarProvider
from bh_ftmo.backtest.engine import run_challenge
from bh_ftmo.backtest.metrics import cohort_metrics
from bh_ftmo.backtest.reporter import render_html_report, write_csv_ledger
from bh_ftmo.backtest.swap import SwapRates
from bh_ftmo.backtest.types import ChallengeResult, GateCriterion, GateResult, PairSpec, Trade

BASE_TS = datetime(2026, 1, 12, 0, 0)
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
PAIR_SPECS = {"EUR_USD": PairSpec("EUR_USD", 0.0001, 100_000)}


def _trade(
    *,
    open_ts: datetime,
    pnl: float,
    strategy: str = "bh_ftmo",
    symbol: str = "EUR_USD",
    components: dict[str, float] | None = None,
) -> Trade:
    return Trade(
        symbol=symbol,
        strategy=strategy,
        direction=1,
        open_ts=open_ts,
        open_price=1.1000,
        close_ts=open_ts + timedelta(hours=4),
        close_price=1.1010,
        stop=1.0990,
        target=1.1020,
        lots=1.0,
        risk_at_open_account_ccy=100.0,
        pnl_account_ccy=pnl,
        swap_account_ccy=-1.0,
        commission_account_ccy=2.0,
        exit_reason="target",
        components=components or {"edge": 1.0},
    )


def _result(
    *,
    trades: tuple[Trade, ...],
    outcome: str = "passed",
    strategy_offset: float = 0.0,
) -> ChallengeResult:
    equity_curve = pd.Series(
        [100_000.0 + strategy_offset, 100_500.0 + strategy_offset, 100_250.0 + strategy_offset, 101_000.0 + strategy_offset],
        index=pd.date_range(BASE_TS, periods=4, freq="1h"),
        dtype=float,
    )
    equity_curve_daily = pd.Series(
        [100_000.0 + strategy_offset, 101_000.0 + strategy_offset],
        index=pd.date_range(BASE_TS, periods=2, freq="1D"),
        dtype=float,
    )
    return ChallengeResult(
        start_ts=equity_curve.index[0].to_pydatetime(),
        end_ts=equity_curve.index[-1].to_pydatetime(),
        outcome=outcome,  # type: ignore[arg-type]
        failed_by=None,
        target_hit_at=None,
        trading_days=1,
        final_equity_account_ccy=float(equity_curve.iloc[-1]),
        trades=trades,
        breaches=(),
        equity_curve=equity_curve,
        equity_curve_daily=equity_curve_daily,
        skipped_signals=(),
        rng_seed=3,
    )




def _gate_result(*, passed: bool, notes: str = 'all clear') -> GateResult:
    return GateResult(
        overall_passed=passed,
        criteria=(
            GateCriterion(name='sharpe', threshold=1.0, actual=1.2 if passed else 0.8, passed=passed),
            GateCriterion(name='vs_best_baseline', threshold=10.0, actual=12.0 if passed else 5.0, passed=passed),
        ),
        bh_ftmo_pass_rate=0.82,
        best_baseline_name='random_baseline',
        best_baseline_pass_rate=0.70,
        margin_vs_best_baseline_pp=12.0 if passed else 5.0,
        notes=notes,
    )

def _signal(ts: datetime, strategy: str = "bh_ftmo") -> Signal:
    return Signal(
        symbol="EUR_USD",
        strategy=strategy,
        timestamp=ts,
        direction=1,
        score=1.0,
        components={"edge": 1.0},
        above_threshold=True,
    )


def _frame_4h(rows: list[tuple[datetime, float, float, float, float]]) -> pd.DataFrame:
    frame = pd.DataFrame(
        [
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
    )
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    return frame


def _frame_1h(rows: list[tuple[datetime, float, float, float, float]]) -> pd.DataFrame:
    frame = pd.DataFrame(
        [
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
    )
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    return frame


def _engine_result(strategy: str = "bh_ftmo") -> ChallengeResult:
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
    return run_challenge(
        bars_4h=bars_4h,
        bars_1h=bars_1h,
        signals=[_signal(t0, strategy=strategy)],
        atr_by_symbol=atr,
        pair_specs=PAIR_SPECS,
        ftmo_config=dict(BASE_CONFIG),
        sizing_config={"risk_pct_per_trade": 0.006, "k_stop": 1.5, "k_target": 2.5},
        swap_rates_by_symbol={"EUR_USD": SwapRates(0.0, 0.0)},
        calendar_provider=NullCalendarProvider(),
        start_ts=t0,
        start_equity=100_000.0,
        rng_seed=7,
    )


def test_write_csv_ledger_single_strategy_has_expected_columns(tmp_path):
    trades = tuple(_trade(open_ts=BASE_TS + timedelta(hours=4 * idx), pnl=25.0 * idx) for idx in range(5))
    output_path = tmp_path / "single.csv"
    write_csv_ledger({"bh_ftmo": _result(trades=trades)}, output_path)
    frame = pd.read_csv(output_path)
    assert len(frame) == 5
    assert list(frame.columns) == [
        "strategy",
        "symbol",
        "direction",
        "open_ts",
        "open_price",
        "close_ts",
        "close_price",
        "stop",
        "target",
        "lots",
        "risk_at_open_account_ccy",
        "pnl_account_ccy",
        "swap_account_ccy",
        "commission_account_ccy",
        "exit_reason",
        "components_json",
    ]


def test_write_csv_ledger_multi_strategy_distinguishes_rows(tmp_path):
    output_path = tmp_path / "multi.csv"
    write_csv_ledger(
        {
            "bh_ftmo": _result(trades=(_trade(open_ts=BASE_TS, pnl=100.0),)),
            "baseline": _result(trades=(_trade(open_ts=BASE_TS, pnl=-50.0, strategy="baseline"),)),
        },
        output_path,
    )
    frame = pd.read_csv(output_path)
    assert sorted(frame["strategy"].tolist()) == ["baseline", "bh_ftmo"]
    assert frame["symbol"].tolist() == ["EUR_USD", "EUR_USD"]


def test_write_csv_ledger_components_json_round_trips(tmp_path):
    output_path = tmp_path / "components.csv"
    trade = _trade(open_ts=BASE_TS, pnl=10.0, components={"edge": 1.5, "cluster": 2.0})
    write_csv_ledger({"bh_ftmo": _result(trades=(trade,))}, output_path)
    frame = pd.read_csv(output_path)
    assert json.loads(frame.loc[0, "components_json"]) == {"cluster": 2.0, "edge": 1.5}


def test_render_html_report_single_strategy_writes_expected_sections(tmp_path):
    output_path = tmp_path / "report.html"
    render_html_report({"bh_ftmo": _result(trades=(_trade(open_ts=BASE_TS, pnl=100.0),))}, output_path)
    html = output_path.read_text(encoding="utf-8")
    assert "<html" in html
    assert "</html>" in html
    assert "<body" in html
    assert "</body>" in html
    assert "Per-Strategy Summary" in html
    assert "Equity Curves" in html
    assert "Worst-DD Chain Visualization" in html
    assert "Trade Ledger Preview" in html


def test_render_html_report_multi_strategy_lists_all_strategies(tmp_path):
    output_path = tmp_path / "multi.html"
    render_html_report(
        {
            "bh_ftmo": _result(trades=(_trade(open_ts=BASE_TS, pnl=100.0, strategy="bh_ftmo"),)),
            "baseline_a": _result(trades=(_trade(open_ts=BASE_TS, pnl=-50.0, strategy="baseline_a"),), strategy_offset=500.0),
        },
        output_path,
    )
    html = output_path.read_text(encoding="utf-8")
    assert "bh_ftmo" in html
    assert "baseline_a" in html
    assert "Per-Strategy Breakdown" in html


def test_render_html_report_with_cohort_metrics_shows_histogram_section_and_bounds(tmp_path):
    output_path = tmp_path / "cohort.html"
    cohort_results = {
        "bh_ftmo": [_result(trades=(_trade(open_ts=BASE_TS, pnl=100.0),), outcome="passed") for _ in range(3)]
        + [_result(trades=(_trade(open_ts=BASE_TS, pnl=-50.0),), outcome="failed") for _ in range(2)]
    }
    metrics = {"bh_ftmo": cohort_metrics(cohort_results["bh_ftmo"], bootstrap_b=1000, rng_seed=0)}
    render_html_report(
        {"bh_ftmo": _result(trades=(_trade(open_ts=BASE_TS, pnl=100.0),))},
        output_path,
        cohort_metrics_by_strategy=metrics,
        cohort_results_by_strategy=cohort_results,
    )
    html = output_path.read_text(encoding="utf-8")
    assert "Pass-Rate Bootstrap CI Histogram" in html
    assert f"{metrics['bh_ftmo'].pass_rate_lower_ci_95 * 100:.1f}%" in html
    assert f"{metrics['bh_ftmo'].pass_rate_upper_ci_95 * 100:.1f}%" in html


def test_render_html_report_without_cohort_metrics_omits_histogram_section(tmp_path):
    output_path = tmp_path / "no_cohort.html"
    render_html_report({"bh_ftmo": _result(trades=(_trade(open_ts=BASE_TS, pnl=100.0),))}, output_path)
    html = output_path.read_text(encoding="utf-8")
    assert "Pass-Rate Bootstrap CI Histogram" not in html


def test_render_html_report_with_no_gate_result_shows_placeholder(tmp_path):
    output_path = tmp_path / "gate.html"
    render_html_report({"bh_ftmo": _result(trades=(_trade(open_ts=BASE_TS, pnl=100.0),))}, output_path)
    html = output_path.read_text(encoding="utf-8")
    assert "Gate evaluation not yet run (sub-phase 3.4)." in html


def test_render_html_report_embeds_non_empty_base64_images(tmp_path):
    output_path = tmp_path / "images.html"
    render_html_report({"bh_ftmo": _result(trades=(_trade(open_ts=BASE_TS, pnl=100.0),))}, output_path)
    html = output_path.read_text(encoding="utf-8")
    matches = re.findall(r'src="data:image/png;base64,([^"]+)"', html)
    assert matches
    assert all(match.strip() for match in matches)


def test_reporter_accepts_engine_generated_challenge_result_for_csv_and_html(tmp_path):
    result = _engine_result()
    csv_path = tmp_path / "engine.csv"
    html_path = tmp_path / "engine.html"
    write_csv_ledger({"bh_ftmo": result}, csv_path)
    render_html_report({"bh_ftmo": result}, html_path)
    assert csv_path.exists()
    assert html_path.exists()
    assert "bh_ftmo" in html_path.read_text(encoding="utf-8")


def test_reporter_accepts_multi_strategy_engine_results(tmp_path):
    bh_result = _engine_result("bh_ftmo")
    baseline_result = _engine_result("baseline")
    html_path = tmp_path / "engine_multi.html"
    render_html_report({"bh_ftmo": bh_result, "baseline": baseline_result}, html_path)
    html = html_path.read_text(encoding="utf-8")
    assert "bh_ftmo" in html
    assert "baseline" in html
    assert "Per-Strategy Breakdown" in html


def test_render_html_report_with_gate_result_passed_shows_green_verdict(tmp_path):
    output_path = tmp_path / 'gate_pass.html'
    render_html_report(
        {'bh_ftmo': _result(trades=(_trade(open_ts=BASE_TS, pnl=100.0),))},
        output_path,
        gate_result=_gate_result(passed=True),
    )
    html = output_path.read_text(encoding='utf-8')
    assert 'Phase 3 Entry-Edge Gate' in html
    assert 'VERDICT: PASSED' in html
    assert 'verdict-passed' in html
    assert 'pill-pass' in html


def test_render_html_report_with_gate_result_failed_shows_red_verdict_and_failed_criteria(tmp_path):
    output_path = tmp_path / 'gate_fail.html'
    render_html_report(
        {'bh_ftmo': _result(trades=(_trade(open_ts=BASE_TS, pnl=100.0),))},
        output_path,
        gate_result=_gate_result(passed=False, notes='baseline margin failed'),
    )
    html = output_path.read_text(encoding='utf-8')
    assert 'VERDICT: FAILED' in html
    assert 'verdict-failed' in html
    assert 'pill-fail' in html
    assert 'baseline margin failed' in html


def test_render_html_report_with_gate_result_lists_best_baseline_and_margin(tmp_path):
    output_path = tmp_path / 'gate_margin.html'
    render_html_report(
        {'bh_ftmo': _result(trades=(_trade(open_ts=BASE_TS, pnl=100.0),))},
        output_path,
        gate_result=_gate_result(passed=True),
    )
    html = output_path.read_text(encoding='utf-8')
    assert 'Best baseline: random_baseline' in html
    assert 'BH FTMO margin: 12.0pp' in html


def test_csv_ledger_includes_risk_at_open_column(tmp_path):
    output_path = tmp_path / 'risk.csv'
    write_csv_ledger({'bh_ftmo': _result(trades=(_trade(open_ts=BASE_TS, pnl=10.0),))}, output_path)
    frame = pd.read_csv(output_path)
    assert 'risk_at_open_account_ccy' in frame.columns
    assert frame.loc[0, 'risk_at_open_account_ccy'] == 100.0
