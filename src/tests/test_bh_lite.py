"""Tests for BH Lite FTMO signal generator."""

import json
import os
import time

import numpy as np
import pandas as pd

from bh_lite import (
    LiteTrader,
    calculate_position_size,
    calculate_t1_t2,
    enrich_dataframe,
    fetch_intraday_ohlcv,
    fetch_ohlcv,
    format_output,
    load_config,
    load_positions,
    rank_signals,
    score_instrument,
    summarize_positions,
)


def make_ohlcv(days=200, start_price=100.0, trend=0.001):
    """Generate synthetic daily OHLCV DataFrame."""
    rng = np.random.default_rng(42)
    dates = pd.bdate_range(end=pd.Timestamp("2026-04-17"), periods=days)
    prices = [start_price]
    for _ in range(1, days):
        prices.append(prices[-1] * (1 + trend + rng.normal(0, 0.015)))
    df = pd.DataFrame({
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "open": [p * (1 + rng.uniform(-0.005, 0.005)) for p in prices],
        "high": [p * (1 + rng.uniform(0.005, 0.02)) for p in prices],
        "low": [p * (1 - rng.uniform(0.005, 0.02)) for p in prices],
        "close": prices,
        "volume": [int(rng.uniform(1e6, 5e6)) for _ in prices],
    })
    return df


def test_load_config(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"account": {"size": 100000}, "risk": {}, "instruments": [{"symbol": "EURUSD=X"}]}))

    config = load_config(str(path))

    assert config["account"]["size"] == 100000
    assert "risk" in config
    assert config["instruments"][0]["symbol"] == "EURUSD=X"


def test_load_positions_empty_file(tmp_path):
    path = tmp_path / "positions.json"
    path.write_text("[]")

    assert load_positions(str(path)) == []


def test_load_positions_missing_file(tmp_path):
    assert load_positions(str(tmp_path / "missing.json")) == []


def test_load_positions_with_data(tmp_path):
    position = {
        "ftmo_symbol": "GSPC.sim",
        "name": "S&P 500",
        "side": "buy",
        "entry": 6967.38,
        "stop": 6821.54,
        "lots": 6.8,
        "risk_usd": 992.0,
        "opened": "2026-04-15",
    }
    path = tmp_path / "positions.json"
    path.write_text(json.dumps([position]))

    assert load_positions(str(path)) == [position]


def test_summarize_positions():
    positions = [{"risk_usd": 992.0}, {"risk_usd": 500.5}]

    summary = summarize_positions(positions)

    assert summary == {"total_risk_usd": 1492.5, "count": 2}


def test_fetch_ohlcv_columns(mocker):
    now = int(time.time())
    timestamps = [now - 86400 * i for i in range(200, 0, -1)]
    prices = [100 + i * 0.1 for i in range(200)]
    mock_resp = mocker.Mock()
    mock_resp.raise_for_status = mocker.Mock()
    mock_resp.json.return_value = {
        "chart": {
            "result": [{
                "timestamp": timestamps,
                "indicators": {
                    "quote": [{
                        "open": prices,
                        "high": [p * 1.01 for p in prices],
                        "low": [p * 0.99 for p in prices],
                        "close": [p + 0.5 for p in prices],
                        "volume": [0] * 200,
                    }]
                },
            }]
        }
    }
    mocker.patch("bh_lite.requests.get", return_value=mock_resp)

    df = fetch_ohlcv("EURUSD=X")

    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume"]
    assert isinstance(df.iloc[0]["date"], str)
    assert pd.api.types.is_numeric_dtype(df["volume"])
    assert df["volume"].min() == 1
    assert len(df) == 200


def test_fetch_intraday_ohlcv_columns(mocker):
    now = int(time.time())
    timestamps = [now - 300 * i for i in range(78, 0, -1)]
    prices = [100 + i * 0.01 for i in range(78)]
    mock_resp = mocker.Mock()
    mock_resp.raise_for_status = mocker.Mock()
    mock_resp.json.return_value = {
        "chart": {
            "result": [{
                "timestamp": timestamps,
                "indicators": {
                    "quote": [{
                        "open": prices,
                        "high": [p * 1.001 for p in prices],
                        "low": [p * 0.999 for p in prices],
                        "close": [p + 0.005 for p in prices],
                        "volume": [1000] * 78,
                    }]
                },
            }]
        }
    }
    mocker.patch("bh_lite.requests.get", return_value=mock_resp)

    df = fetch_intraday_ohlcv("EURUSD=X")

    assert "datetime" in df.columns
    assert list(df.columns) == ["datetime", "open", "high", "low", "close", "volume"]
    assert len(df) == 78


def test_enrich_adds_indicators():
    df = enrich_dataframe(make_ohlcv())

    for col in ["rsi_14", "macd_line", "adx", "avg_volume_20"]:
        assert col in df.columns
    assert df["rsi_14"].notna().any()


def test_zero_volume_does_not_produce_nan():
    """Forex-like data with zero volume should still produce valid setups."""
    df = make_ohlcv()
    df["volume"] = 0
    df["volume"] = df["volume"].replace(0, 1)

    enriched = enrich_dataframe(df)
    setup = LiteTrader().calculate_baseline_setup(enriched, technical_score=5)

    assert not pd.isna(setup["entry_price"])
    assert not pd.isna(setup["stop_loss"])
    assert not pd.isna(setup["take_profit"])


def test_forex_zero_volume_scores_nonzero():
    """Instruments with floored volume should produce non-zero scores."""
    df = make_ohlcv()
    df["volume"] = 1

    enriched = enrich_dataframe(df)
    scores = score_instrument(enriched)

    assert scores["baseline_score"] != 0.0 or scores["mean_reversion_score"] != 0.0


def test_lite_trader_baseline_setup():
    df = enrich_dataframe(make_ohlcv())
    setup = LiteTrader().calculate_baseline_setup(df, technical_score=10)
    close = df.iloc[-1]["close"]

    assert setup["entry_price"] < close
    assert setup["stop_loss"] < setup["entry_price"]
    assert setup["take_profit"] > setup["entry_price"]
    assert setup["rr_ratio"] > 0


def test_lite_trader_mr_setup():
    df = enrich_dataframe(make_ohlcv())
    setup = LiteTrader().calculate_mean_reversion_setup(df)

    assert setup["entry_price"] == df.iloc[-1]["close"]
    assert setup["stop_loss"] < setup["entry_price"]
    assert setup["take_profit"] > setup["entry_price"]
    assert setup["rr_ratio"] > 0


def test_t1_t2_split():
    targets = calculate_t1_t2(100, 95, 112)

    assert targets == {"t1": 105, "t2": 112}


def test_position_sizing_forex():
    instrument = {"type": "forex", "pip_size": 0.0001, "dollar_per_pip_per_lot": 10.0, "min_lot": 0.01}
    risk = {"max_risk_per_trade_pct": 0.01, "max_daily_risk_pct": 0.04}
    account = {"size": 100000}

    size = calculate_position_size(1.1000, 1.0900, instrument, risk, account, 0)

    assert size["lots"] == 1.0
    assert size["risk_usd"] == 1000
    assert size["skipped"] is False


def test_position_sizing_commodity():
    instrument = {"type": "commodity", "contract_size": 100, "min_lot": 0.01}
    risk = {"max_risk_per_trade_pct": 0.01, "max_daily_risk_pct": 0.04}
    account = {"size": 100000}

    size = calculate_position_size(2000, 1990, instrument, risk, account, 0)

    assert size["lots"] == 1.0
    assert size["risk_usd"] == 1000


def test_daily_risk_budget_exhausted():
    instrument = {"type": "forex", "pip_size": 0.0001, "dollar_per_pip_per_lot": 10.0, "min_lot": 0.01}
    risk = {"max_risk_per_trade_pct": 0.01, "max_daily_risk_pct": 0.04}
    account = {"size": 100000}

    size = calculate_position_size(1.1000, 1.0900, instrument, risk, account, 4000)

    # Still shows full recommended size, but flags over_budget
    assert size["lots"] == 1.0
    assert size["risk_usd"] == 1000
    assert size["over_budget"] is True


def test_positions_reduce_budget():
    position = {
        "ftmo_symbol": "GSPC.sim",
        "name": "S&P 500",
        "side": "buy",
        "entry": 6967.38,
        "stop": 6821.54,
        "lots": 6.8,
        "risk_usd": 992.0,
        "opened": "2026-04-15",
    }
    account = {"size": 100000, "currency": "USD"}
    risk = {"max_risk_per_trade_pct": 0.01, "max_daily_risk_pct": 0.04, "max_concurrent_positions": 3}
    instrument = {"type": "commodity", "contract_size": 100, "min_lot": 0.01}

    summary = summarize_positions([position])
    size = calculate_position_size(2000, 1990, instrument, risk, account, summary["total_risk_usd"])
    output = format_output([], account, risk, summary["total_risk_usd"], [position])

    assert size["risk_usd"] == 1000
    assert "Remaining daily risk: $3,008.00" in output
    assert "Positions: 1/3 | Daily risk committed: $992.00 / $4,000.00" in output


def test_max_concurrent_reached():
    positions = [{"risk_usd": 100}, {"risk_usd": 200}, {"risk_usd": 300}]
    risk = {"max_concurrent_positions": 3}
    signals = [
        {
            "instrument": {"name": "A"},
            "baseline_score": 10,
            "baseline_setup": {"is_realistic": True, "rr_ratio": 1.0},
            "mean_reversion_score": 8,
            "mean_reversion_setup": {"is_realistic": True, "rr_ratio": 1.0},
        }
    ]

    assert rank_signals(signals, top_n=5)[0]["instrument"]["name"] == "A"


def test_rank_signals():
    signals = [
        {
            "instrument": {"name": "A"},
            "baseline_score": 5,
            "baseline_setup": {"is_realistic": True, "rr_ratio": 1.0},
            "mean_reversion_score": 2,
            "mean_reversion_setup": {"is_realistic": True, "rr_ratio": 1.0},
        },
        {
            "instrument": {"name": "B"},
            "baseline_score": 10,
            "baseline_setup": {"is_realistic": True, "rr_ratio": 1.0},
            "mean_reversion_score": 12,
            "mean_reversion_setup": {"is_realistic": True, "rr_ratio": 1.0},
        },
        {
            "instrument": {"name": "C"},
            "baseline_score": 99,
            "baseline_setup": {"is_realistic": False, "rr_ratio": 3.0},
            "mean_reversion_score": 98,
            "mean_reversion_setup": {"is_realistic": True, "rr_ratio": 0.2},
        },
    ]

    ranked = rank_signals(signals)

    assert [item["instrument"]["name"] for item in ranked] == ["B", "A"]
    assert ranked[0]["strategy"] == "MeanRev"


def test_find_instrument_by_ftmo():
    from bh_lite import _find_instrument_by_ftmo

    config = {
        "instruments": [
            {"symbol": "AUDJPY=X", "ftmo": "AUDJPY.sim", "type": "forex"},
            {"symbol": "^GSPC", "name": "S&P 500", "type": "index"},
        ]
    }

    assert _find_instrument_by_ftmo("AUDJPY.sim", config)["symbol"] == "AUDJPY=X"
    assert _find_instrument_by_ftmo("GSPC.sim", config)["symbol"] == "^GSPC"


def test_find_instrument_by_ftmo_unknown():
    from bh_lite import _find_instrument_by_ftmo

    config = {"instruments": [{"symbol": "AUDJPY=X", "ftmo": "AUDJPY.sim"}]}

    assert _find_instrument_by_ftmo("UNKNOWN.sim", config) is None


def test_position_health_ok(mocker):
    from bh_lite import check_position_health

    df = make_ohlcv(start_price=100.0)
    df.loc[df.index[-1], "close"] = 104.0
    config = {"instruments": [{"symbol": "^GSPC", "name": "S&P 500", "type": "index", "contract_size": 1}]}
    position = {"ftmo_symbol": "GSPC.sim", "side": "buy", "entry": 100.0, "stop": 90.0, "lots": 2.0}
    mocker.patch("bh_lite.fetch_ohlcv", return_value=df)
    mocker.patch("bh_lite.score_instrument", return_value={"baseline_score": 20.0, "mean_reversion_score": 12.0})

    health = check_position_health(position, config)

    assert health["status"] == "OK"
    assert health["warnings"] == []
    assert health["current_strategy"] == "Baseline"
    assert health["pnl_usd"] == 8.0


def test_position_health_weakening(mocker):
    from bh_lite import check_position_health

    df = make_ohlcv(start_price=100.0)
    df.loc[df.index[-1], "close"] = 99.0
    config = {"instruments": [{"symbol": "^GSPC", "name": "S&P 500", "type": "index", "contract_size": 1}]}
    position = {"ftmo_symbol": "GSPC.sim", "side": "buy", "entry": 100.0, "stop": 90.0, "lots": 2.0}
    mocker.patch("bh_lite.fetch_ohlcv", return_value=df)
    mocker.patch("bh_lite.score_instrument", return_value={"baseline_score": 3.0, "mean_reversion_score": 2.0})

    health = check_position_health(position, config)

    assert health["status"] == "WEAKENING"
    assert any("Score below 5.0" in warning for warning in health["warnings"])


def test_position_health_critical(mocker):
    from bh_lite import check_position_health

    df = make_ohlcv(start_price=100.0)
    df.loc[df.index[-1], "close"] = 98.0
    config = {"instruments": [{"symbol": "^GSPC", "name": "S&P 500", "type": "index", "contract_size": 1}]}
    position = {"ftmo_symbol": "GSPC.sim", "side": "buy", "entry": 100.0, "stop": 97.5, "lots": 2.0}
    mocker.patch("bh_lite.fetch_ohlcv", return_value=df)
    mocker.patch("bh_lite.score_instrument", return_value={"baseline_score": 0.0, "mean_reversion_score": -1.0})

    health = check_position_health(position, config)

    assert health["status"] == "CRITICAL"
    assert any("Score collapsed" in warning for warning in health["warnings"])


def test_position_pnl_forex():
    from bh_lite import _calculate_position_pnl

    position = {"side": "buy", "entry": 1.1000, "lots": 1.0}
    instrument = {"type": "forex", "pip_size": 0.0001, "dollar_per_pip_per_lot": 10.0}

    pnl_usd, pnl_pct = _calculate_position_pnl(position, instrument, 1.1050)

    assert pnl_usd == 500.0
    assert pnl_pct == 0.45
