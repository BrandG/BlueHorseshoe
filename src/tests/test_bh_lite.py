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
    fetch_ohlcv,
    load_config,
    rank_signals,
    score_instrument,
)


def make_ohlcv(days=200, start_price=100.0, trend=0.001):
    """Generate synthetic daily OHLCV DataFrame."""
    rng = np.random.default_rng(42)
    dates = pd.bdate_range(end=pd.Timestamp.today(), periods=days)
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

    assert size == {"lots": 0, "risk_usd": 0, "skipped": True}


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
