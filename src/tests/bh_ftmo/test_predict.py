from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from bh_ftmo.analysis.cluster_filter import cluster_filter
from bh_ftmo.analysis.strategy import Signal
from bh_ftmo.backtest.pip_value import quote_to_account_rate
from bh_ftmo.backtest.trade_factory import derive_position
from bh_ftmo import predict


BASE_TS = datetime(2026, 4, 20)


class FakeStore:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self.frames = frames

    def load(self, symbol: str, *, granularity: str, start=None, end=None, include_incomplete=True):
        assert granularity == "H4"
        frame = self.frames[symbol]
        ts = pd.to_datetime(frame["timestamp"])
        mask = pd.Series(True, index=frame.index)
        if start is not None:
            mask &= ts >= pd.Timestamp(start)
        if end is not None:
            mask &= ts < pd.Timestamp(end)
        if not include_incomplete:
            mask &= frame["is_complete"]
        return frame.loc[mask].reset_index(drop=True)


def _bar_frame(
    symbol: str,
    *,
    periods: int = 24,
    start: datetime = BASE_TS,
    price: float = 1.1000,
    spread: float = 0.0001,
) -> pd.DataFrame:
    rows = []
    for i in range(periods):
        mid = price + (i * 0.001)
        bid = mid - spread / 2
        ask = mid + spread / 2
        rows.append(
            {
                "timestamp": start + timedelta(hours=4 * i),
                "open_bid": bid,
                "high_bid": bid + 0.0010,
                "low_bid": bid - 0.0010,
                "close_bid": bid + 0.0004,
                "open_ask": ask,
                "high_ask": ask + 0.0010,
                "low_ask": ask - 0.0010,
                "close_ask": ask + 0.0004,
                "tick_volume": 100,
                "provider": "test",
                "ingested_at": start,
                "is_complete": i < periods - 1,
            }
        )
    return pd.DataFrame(rows)


def _write_config(path: Path, symbols: list[str]) -> Path:
    pip_sizes = {
        "EUR_USD": 0.0001,
        "EUR_GBP": 0.0001,
        "GBP_USD": 0.0001,
        "USD_CAD": 0.0001,
        "CAD_JPY": 0.01,
    }
    payload = {
        "ftmo": {"account_currency": "USD"},
        "risk": {"max_risk_per_trade_pct": 0.01, "max_concurrent_positions": 3},
        "instruments": [
            {
                "symbol": symbol.replace("_", "") + "=X",
                "name": symbol.replace("_", "/"),
                "ftmo": symbol.replace("_", "") + ".sim",
                "type": "forex",
                "pip_size": pip_sizes[symbol],
                "min_lot": 0.01,
            }
            for symbol in symbols
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_weights(path: Path, *, universe_enabled: bool = False, sandbox_enabled=None) -> Path:
    sandbox = {
        "min_score_threshold": 0.5,
        "components": {
            "stoch_oversold_cross_long": 1.0,
            "sma_cross_long": 1.0,
            "rsi_overbought_cross_short": 1.0,
        },
        "short_pair_whitelist": ["CAD_JPY", "USD_CAD"],
        "universe_filter": {
            "enabled": universe_enabled,
            "stop_pct": 0.005,
            "max_spread_to_stop_ratio": 0.05,
            "lookback_days": 30,
        },
    }
    if sandbox_enabled is not None:
        sandbox["enabled"] = sandbox_enabled
    path.write_text(json.dumps({"sandbox_v1": sandbox}), encoding="utf-8")
    return path


def _signal(symbol: str, ts: datetime, *, score: float = 1.0, direction: int = 1) -> Signal:
    return Signal(
        symbol=symbol,
        strategy="sandbox_v1",
        timestamp=ts,
        direction=direction,
        score=score,
        components={"test": score},
        above_threshold=True,
    )


def _run(tmp_path, monkeypatch, frames, emitted: list[Signal], *, weights_kwargs=None):
    weights_kwargs = weights_kwargs or {}
    config = _write_config(tmp_path / "config.json", list(frames))
    weights = _write_weights(tmp_path / "weights.json", **weights_kwargs)
    output = tmp_path / "report.html"
    monkeypatch.setattr(predict, "_generate_bh_ftmo_signals", lambda bars, weights_path, symbols, strategy_names: emitted)
    return predict.run_prediction(
        equity=10_000,
        target_date=date(2026, 4, 24),
        config_path=config,
        weights_path=weights,
        db_path=tmp_path / "missing.duckdb",
        output_html=output,
        symbols_arg=None,
        strategies_arg=None,
        lookback_days=30,
        email=False,
        store=FakeStore(frames),
    )


def test_predict_with_no_signals_returns_clean_empty_report(tmp_path, monkeypatch):
    frames = {"EUR_USD": _bar_frame("EUR_USD")}

    console, html_path, live_signals, *_ = _run(tmp_path, monkeypatch, frames, [])

    assert live_signals == []
    assert "No signals fired this bar." in console
    assert "No signals fired this bar." in html_path.read_text(encoding="utf-8")


def test_predict_emits_signal_from_most_recent_complete_bar(tmp_path, monkeypatch):
    frames = {"EUR_USD": _bar_frame("EUR_USD")}
    signal_ts = frames["EUR_USD"]["timestamp"].iloc[-2]
    emitted = [_signal("EUR_USD", signal_ts)]

    console, _, live_signals, selected_signal_ts, entry_ts, *_ = _run(tmp_path, monkeypatch, frames, emitted)

    assert selected_signal_ts == signal_ts
    assert entry_ts == frames["EUR_USD"]["timestamp"].iloc[-1]
    assert len(live_signals) == 1
    assert "EUR_USD" in console


def test_predict_position_sizing_matches_backtest(tmp_path, monkeypatch):
    frames = {"EUR_USD": _bar_frame("EUR_USD")}
    signal_ts = frames["EUR_USD"]["timestamp"].iloc[-2]
    emitted = [_signal("EUR_USD", signal_ts)]

    _, _, live_signals, selected_signal_ts, entry_ts, *_ = _run(tmp_path, monkeypatch, frames, emitted)

    config = predict._load_full_config(tmp_path / "config.json")
    pair_specs = predict._build_pair_specs(config)
    atr_by_symbol = predict._compute_atr_by_symbol(frames)
    rates = predict._rates_snapshot_at(frames, entry_ts)
    expected = derive_position(
        emitted[0],
        next_bar=predict._row_at(frames["EUR_USD"], entry_ts),
        atr_14=float(atr_by_symbol["EUR_USD"].loc[pd.Timestamp(selected_signal_ts)]),
        pair_spec=pair_specs["EUR_USD"],
        sizing_config={"risk_pct_per_trade": 0.01, "k_stop": 1.5, "k_target": 2.5, "max_concurrent_positions": 3},
        account_currency="USD",
        current_equity=10_000,
        quote_to_account=quote_to_account_rate("EUR_USD", "USD", rates),
        next_position_id=1,
    )
    assert expected is not None
    assert live_signals[0].position.lots == pytest.approx(expected.lots)


def test_predict_universe_filter_drops_pairs(tmp_path, monkeypatch):
    frames = {
        "EUR_USD": _bar_frame("EUR_USD", spread=0.0001),
        "USD_CAD": _bar_frame("USD_CAD", price=1.35, spread=0.05),
    }
    signal_ts = frames["EUR_USD"]["timestamp"].iloc[-2]
    emitted = [_signal("EUR_USD", signal_ts), _signal("USD_CAD", signal_ts, score=2.0)]

    _, _, live_signals, *_ = _run(
        tmp_path,
        monkeypatch,
        frames,
        emitted,
        weights_kwargs={"universe_enabled": True},
    )

    assert [item.signal.symbol for item in live_signals] == ["EUR_USD"]


def test_predict_cluster_filter_dedups_correlated_signals(tmp_path, monkeypatch):
    frames = {"EUR_USD": _bar_frame("EUR_USD", price=1.10)}
    signal_ts = frames["EUR_USD"]["timestamp"].iloc[-2]
    raw = [_signal("EUR_USD", signal_ts, score=1.0), _signal("EUR_USD", signal_ts, score=2.0)]
    config = _write_config(tmp_path / "config.json", list(frames))
    weights = _write_weights(tmp_path / "weights.json")
    output = tmp_path / "report.html"
    monkeypatch.setattr(
        predict,
        "_generate_bh_ftmo_signals",
        lambda bars, weights_path, symbols, strategy_names: cluster_filter(raw),
    )

    _, _, live_signals, *_ = predict.run_prediction(
        equity=10_000,
        target_date=date(2026, 4, 24),
        config_path=config,
        weights_path=weights,
        db_path=tmp_path / "missing.duckdb",
        output_html=output,
        symbols_arg=None,
        strategies_arg=None,
        lookback_days=30,
        email=False,
        store=FakeStore(frames),
    )

    assert [(item.signal.symbol, item.signal.score) for item in live_signals] == [("EUR_USD", 2.0)]


def test_predict_html_report_has_expected_columns(tmp_path, monkeypatch):
    import re

    frames = {"EUR_USD": _bar_frame("EUR_USD")}

    _, html_path, *_ = _run(tmp_path, monkeypatch, frames, [])
    html = html_path.read_text(encoding="utf-8")

    for header in ["Pair", "Strategy", "Direction", "Score", "Entry", "Stop", "Target", "Lots", "Risk$"]:
        assert re.search(rf"<th[^>]*>{re.escape(header)}</th>", html), f"missing header: {header}"


def test_predict_email_disabled_with_flag(tmp_path, monkeypatch):
    frames = {"EUR_USD": _bar_frame("EUR_USD")}
    monkeypatch.setattr(predict, "send_failure_email", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("smtp attempted")))

    _run(tmp_path, monkeypatch, frames, [])


def test_predict_loads_strategy_from_weights(tmp_path, monkeypatch):
    frames = {"EUR_USD": _bar_frame("EUR_USD")}
    captured: list[list[str]] = []

    def fake_generate(bars, weights_path, symbols, strategy_names):
        captured.append(list(strategy_names))
        return []

    config = _write_config(tmp_path / "config.json", list(frames))
    weights = _write_weights(tmp_path / "weights.json", sandbox_enabled=False)
    monkeypatch.setattr(predict, "_generate_bh_ftmo_signals", fake_generate)

    predict.run_prediction(
        equity=10_000,
        target_date=date(2026, 4, 24),
        config_path=config,
        weights_path=weights,
        db_path=tmp_path / "missing.duckdb",
        output_html=tmp_path / "report.html",
        symbols_arg=None,
        strategies_arg=None,
        lookback_days=30,
        email=False,
        store=FakeStore(frames),
    )

    assert captured == [[]]


def test_predict_real_data_smoke(tmp_path):
    db_path = predict.DEFAULT_DB_PATH
    if not db_path.exists():
        pytest.skip("data/fx_4h.duckdb unavailable")
    output = tmp_path / "real.html"
    rc = predict.main(["--equity", "10000", "--no-email", "--output-html", str(output)])
    assert rc == 0
    assert output.exists()
