"""Tests for the Phase 3.5 CLI driver."""

from __future__ import annotations

# pylint: disable=missing-function-docstring
import io
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from bh_ftmo.analysis.strategy import Signal
from bh_ftmo.backtest import cli


BASE_CONFIG = {
    "ftmo": {
        "initial_balance": 100000,
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
    },
    "risk": {
        "max_risk_per_trade_pct": 0.005,
        "max_daily_risk_pct": 0.04,
        "max_concurrent_positions": 3,
        "t1_split_pct": 0.5,
    },
    "instruments": [
        {"ftmo": "EURUSD.sim", "pip_size": 0.0001},
        {"ftmo": "GBPUSD.sim", "pip_size": 0.0001},
    ],
}

WEIGHTS = {
    "baseline": {"min_score_threshold": 3.0, "direction": 1, "components": {"trend_above_ema_50": 1.0}},
    "mean_reversion": {"min_score_threshold": 3.0, "components": {"mr_rsi_oversold": 1.0}},
}


def _write_config(path: Path, *, placeholder: bool = False) -> Path:
    payload = json.loads(json.dumps(BASE_CONFIG))
    if placeholder:
        payload["ftmo"]["swap_model"] = "PLACEHOLDER_STANDARD"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_weights(path: Path) -> Path:
    path.write_text(json.dumps(WEIGHTS), encoding="utf-8")
    return path


def _bars_4h(start: datetime, periods: int = 200) -> pd.DataFrame:
    timestamps = pd.date_range(start, periods=periods, freq="4h")
    open_bid = pd.Series([1.10 + (idx * 0.0003) for idx in range(periods)])
    frame = pd.DataFrame({"timestamp": timestamps})
    frame["open_bid"] = open_bid
    frame["open_ask"] = open_bid + 0.0002
    frame["close_bid"] = open_bid + 0.0004
    frame["close_ask"] = frame["close_bid"] + 0.0002
    frame["high_bid"] = frame[["open_bid", "close_bid"]].max(axis=1) + 0.0015
    frame["high_ask"] = frame["high_bid"] + 0.0002
    frame["low_bid"] = frame[["open_bid", "close_bid"]].min(axis=1) - 0.0015
    frame["low_ask"] = frame["low_bid"] + 0.0002
    return frame


def _bars_1h(frame_4h: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for row in frame_4h.itertuples(index=False):
        for step in range(1, 5):
            close_bid = row.open_bid + 0.0001 * step
            rows.append(
                {
                    "timestamp": row.timestamp + timedelta(hours=step),
                    "close_bid": close_bid,
                    "close_ask": close_bid + 0.0002,
                    "high_bid": row.high_bid,
                    "high_ask": row.high_ask,
                    "low_bid": row.low_bid,
                    "low_ask": row.low_ask,
                }
            )
    return pd.DataFrame(rows)


def _synthetic_signals(bars_4h: dict[str, pd.DataFrame], symbols: list[str]) -> list[Signal]:
    out: list[Signal] = []
    for symbol in symbols:
        for ts in pd.to_datetime(bars_4h[symbol]["timestamp"]).tolist()[::10][:8]:
            out.append(
                Signal(
                    symbol=symbol,
                    strategy="bh_ftmo",
                    timestamp=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
                    direction=1,
                    score=5.0,
                    components={"edge": 1.0},
                    above_threshold=True,
                )
            )
    return out


def _run_main(argv: list[str], monkeypatch: pytest.MonkeyPatch) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    monkeypatch.setattr(cli.sys, "stdout", stdout)
    monkeypatch.setattr(cli.sys, "stderr", stderr)
    exit_code = cli.main(argv)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def test_cli_help_lists_all_options(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.build_parser().parse_args(["--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    for flag in [
        "--output-html",
        "--output-csv",
        "--start-date",
        "--end-date",
        "--symbols",
        "--no-swap",
        "--max-workers",
        "--rng-seed",
        "--limit-folds",
        "--limit-starts",
        "--strategies",
        "--config",
        "--weights",
    ]:
        assert flag in out


def test_cli_parser_strategy_default_is_all():
    args = cli.build_parser().parse_args([])
    assert args.strategies is None


def test_cli_parser_strategy_single_value():
    args = cli.build_parser().parse_args(["--strategies", "baseline"])
    assert args.strategies == ["baseline"]


def test_cli_parser_strategy_comma_list():
    args = cli.build_parser().parse_args(["--strategies", "baseline,mean_reversion"])
    assert args.strategies == ["baseline", "mean_reversion"]


def test_cli_parser_strategy_whitespace_tolerant():
    args = cli.build_parser().parse_args(["--strategies", "  baseline , mean_reversion  "])
    assert args.strategies == ["baseline", "mean_reversion"]


def test_cli_parser_strategy_dedupes_order_preserving():
    args = cli.build_parser().parse_args(["--strategies", "baseline,baseline"])
    assert args.strategies == ["baseline"]


def test_cli_parser_strategy_rejects_invalid_value():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["--strategies", "xyz"])


def test_resolve_max_workers_caps_sandbox_default():
    assert cli._resolve_max_workers(["sandbox_v1"], None) == 2


def test_resolve_max_workers_preserves_explicit_request_for_sandbox():
    assert cli._resolve_max_workers(["sandbox_v1"], 4) == 4


def test_resolve_max_workers_leaves_non_sandbox_default_unset():
    assert cli._resolve_max_workers(["baseline", "mean_reversion"], None) is None


def test_cli_exits_2_on_placeholder_config(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path / "config.json", placeholder=True)
    weights_path = _write_weights(tmp_path / "weights.json")
    exit_code, stdout, stderr = _run_main(["--config", str(config_path), "--weights", str(weights_path)], monkeypatch)
    assert exit_code == 2
    assert stdout == ""
    assert "PLACEHOLDER" in stderr


def test_cli_smoke_run_on_synthetic_fixture(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path / "config.json")
    weights_path = _write_weights(tmp_path / "weights.json")
    output_html = tmp_path / "report.html"
    output_csv = tmp_path / "ledger.csv"
    bars_4h = {
        "EUR_USD": _bars_4h(datetime(2024, 1, 1), periods=7000),
        "GBP_USD": _bars_4h(datetime(2024, 1, 1), periods=7000),
    }
    bars_1h = {symbol: _bars_1h(frame) for symbol, frame in bars_4h.items()}

    monkeypatch.setattr(cli, "_load_bars", lambda symbols, start, end, store=None: (bars_4h, bars_1h))
    monkeypatch.setattr(
        cli,
        "_generate_bh_ftmo_signals",
        lambda bars, weights, symbols, strategy_names: _synthetic_signals(bars, symbols),
    )
    monkeypatch.setattr(cli, "_default_window", lambda today=None: (date(2024, 1, 1), date(2026, 12, 31)))

    exit_code, stdout, stderr = _run_main(
        [
            "--config",
            str(config_path),
            "--weights",
            str(weights_path),
            "--output-html",
            str(output_html),
            "--output-csv",
            str(output_csv),
            "--no-swap",
            "--limit-folds",
            "1",
            "--limit-starts",
            "2",
            "--max-workers",
            "1",
        ],
        monkeypatch,
    )
    assert exit_code in {0, 1}
    assert "Verdict:" in stdout
    assert output_html.exists()
    assert output_csv.exists()
    assert stderr == "" or "run_id=" in stderr


def test_cli_run_id_changes_per_invocation(tmp_path):
    args = cli.build_parser().parse_args(["--config", str(tmp_path / "config.json"), "--weights", str(tmp_path / "weights.json")])
    args.start_date = date(2026, 1, 1)
    args.end_date = date(2026, 12, 31)
    args.symbols = ["EUR_USD"]
    first = cli._compute_run_id(args, now_utc=datetime(2026, 4, 25, 15, 30, 12))
    second = cli._compute_run_id(args, now_utc=datetime(2026, 4, 25, 15, 30, 13))
    assert first != second


def test_cli_run_id_changes_with_strategy_selection(tmp_path):
    baseline_args = cli.build_parser().parse_args(
        ["--config", str(tmp_path / "config.json"), "--weights", str(tmp_path / "weights.json"), "--strategies", "baseline"]
    )
    mr_args = cli.build_parser().parse_args(
        ["--config", str(tmp_path / "config.json"), "--weights", str(tmp_path / "weights.json"), "--strategies", "mean_reversion"]
    )
    for args in (baseline_args, mr_args):
        args.start_date = date(2026, 1, 1)
        args.end_date = date(2026, 12, 31)
        args.symbols = ["EUR_USD"]

    baseline_run_id = cli._compute_run_id(baseline_args, now_utc=datetime(2026, 4, 25, 15, 30, 12))
    mr_run_id = cli._compute_run_id(mr_args, now_utc=datetime(2026, 4, 25, 15, 30, 12))
    assert baseline_run_id != mr_run_id


def test_generate_bh_ftmo_signals_honors_strategy_selection(tmp_path, monkeypatch):
    calls: list[str] = []

    class FakeBaselineStrategy:
        name = "baseline"

        def __init__(self, weights: dict) -> None:
            calls.append(self.name)

    class FakeMeanReversionStrategy:
        name = "mean_reversion"

        def __init__(self, weights: dict) -> None:
            calls.append(self.name)

    class FakeSignalGenerator:
        def __init__(self, strategies: list) -> None:
            self.strategies = strategies

        def generate(self, bars_4h: dict[str, pd.DataFrame], symbols: list[str]) -> list[Signal]:
            return []

    monkeypatch.setattr(cli, "load_weights", lambda weights_path: {"baseline": {}, "mean_reversion": {}})
    monkeypatch.setattr(cli, "BaselineStrategy", FakeBaselineStrategy)
    monkeypatch.setattr(cli, "MeanReversionStrategy", FakeMeanReversionStrategy)
    monkeypatch.setattr(cli, "SignalGenerator", FakeSignalGenerator)
    monkeypatch.setattr(cli, "cluster_filter", lambda signals: signals)

    result = cli._generate_bh_ftmo_signals({}, tmp_path / "weights.json", ["EUR_USD"], strategy_names=["baseline"])

    assert result == []
    assert calls == ["baseline"]


def test_cli_passes_seed_into_gate_for_determinism(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path / "config.json")
    weights_path = _write_weights(tmp_path / "weights.json")
    bars_4h = {
        "EUR_USD": _bars_4h(datetime(2024, 1, 1), periods=7000),
        "GBP_USD": _bars_4h(datetime(2024, 1, 1), periods=7000),
    }
    bars_1h = {symbol: _bars_1h(frame) for symbol, frame in bars_4h.items()}

    monkeypatch.setattr(cli, "_load_bars", lambda symbols, start, end, store=None: (bars_4h, bars_1h))
    monkeypatch.setattr(
        cli,
        "_generate_bh_ftmo_signals",
        lambda bars, weights, symbols, strategy_names: _synthetic_signals(bars, symbols),
    )
    monkeypatch.setattr(cli, "_default_window", lambda today=None: (date(2024, 1, 1), date(2026, 12, 31)))

    shared_args = [
        "--config",
        str(config_path),
        "--weights",
        str(weights_path),
        "--no-swap",
        "--limit-folds",
        "1",
        "--limit-starts",
        "2",
        "--max-workers",
        "1",
        "--rng-seed",
        "123",
    ]
    left_csv = tmp_path / "left.csv"
    right_csv = tmp_path / "right.csv"
    left_html = tmp_path / "left.html"
    right_html = tmp_path / "right.html"

    left_code, left_stdout, _ = _run_main(shared_args + ["--output-html", str(left_html), "--output-csv", str(left_csv)], monkeypatch)
    right_code, right_stdout, _ = _run_main(shared_args + ["--output-html", str(right_html), "--output-csv", str(right_csv)], monkeypatch)

    assert left_code == right_code
    assert left_stdout.splitlines()[3] == right_stdout.splitlines()[3]
    assert left_csv.read_text(encoding="utf-8") == right_csv.read_text(encoding="utf-8")
