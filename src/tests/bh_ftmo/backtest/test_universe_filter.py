"""Tests for the cost-survivability universe filter."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from bh_ftmo.backtest.universe_filter import UniverseFilterConfig, apply_universe_filter
from bh_ftmo.data.fx_store import FxStore


REPO_ROOT = Path(__file__).resolve().parents[4]


def _bars(
    *,
    mid: float = 100.0,
    spread: float = 0.01,
    start: datetime = datetime(2026, 1, 1),
    periods: int = 20,
    freq: str = "4h",
) -> pd.DataFrame:
    timestamps = pd.date_range(start, periods=periods, freq=freq)
    bid = mid - spread / 2.0
    ask = mid + spread / 2.0
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open_bid": bid,
            "open_ask": ask,
            "high_bid": bid,
            "high_ask": ask,
            "low_bid": bid,
            "low_ask": ask,
            "close_bid": bid,
            "close_ask": ask,
        }
    )


def test_filter_drops_high_spread_pair():
    config = UniverseFilterConfig(enabled=True, stop_pct=0.005, max_spread_to_stop_ratio=0.05)
    bars = {"WIDE": _bars(mid=100.0, spread=0.05)}

    assert apply_universe_filter(bars, config) == set()


def test_filter_keeps_low_spread_pair():
    config = UniverseFilterConfig(enabled=True, stop_pct=0.005, max_spread_to_stop_ratio=0.05)
    bars = {"TIGHT": _bars(mid=100.0, spread=0.01)}

    assert apply_universe_filter(bars, config) == {"TIGHT"}


def test_filter_at_threshold_keeps_pair():
    config = UniverseFilterConfig(enabled=True, stop_pct=0.005, max_spread_to_stop_ratio=0.05)
    bars = {"EDGE": _bars(mid=100.0, spread=0.025)}

    assert apply_universe_filter(bars, config) == {"EDGE"}


def test_filter_lookback_respected():
    config = UniverseFilterConfig(
        enabled=True,
        stop_pct=0.005,
        max_spread_to_stop_ratio=0.05,
        lookback_days=30,
    )
    wide = _bars(mid=100.0, spread=0.05, periods=29, freq="1D")
    tight = _bars(mid=100.0, spread=0.01, start=datetime(2026, 1, 30), periods=31, freq="1D")
    bars = {"RECENT_TIGHT": pd.concat([wide, tight], ignore_index=True)}

    assert apply_universe_filter(bars, config) == {"RECENT_TIGHT"}


def test_filter_disabled_returns_all_symbols():
    config = UniverseFilterConfig(enabled=False)
    bars = {"WIDE": _bars(mid=100.0, spread=0.05), "EMPTY": pd.DataFrame()}

    assert apply_universe_filter(bars, config) == {"WIDE", "EMPTY"}


def test_filter_missing_bid_ask_drops_pair_defensively(caplog):
    config = UniverseFilterConfig(enabled=True)
    bars = {"BROKEN": pd.DataFrame({"timestamp": [datetime(2026, 1, 1)], "close": [1.0]})}

    assert apply_universe_filter(bars, config) == set()
    assert "missing columns" in caplog.text


def test_filter_empty_bars_drops_pair_defensively(caplog):
    config = UniverseFilterConfig(enabled=True)

    assert apply_universe_filter({"EMPTY": pd.DataFrame()}, config) == set()
    assert "empty bars" in caplog.text


def test_filter_drops_known_exotic_pairs_on_real_data():
    db_path = REPO_ROOT / "data" / "fx_4h.duckdb"
    if not db_path.exists():
        pytest.skip("data/fx_4h.duckdb is not present")

    symbols = ["EUR_USD", "USD_HUF", "USD_CZK", "USD_TRY", "USD_ZAR"]
    store = FxStore(db_path, read_only=True)
    try:
        bars = {symbol: store.load(symbol, granularity="H4") for symbol in symbols}
    finally:
        store.close()
    if any(frame.empty for frame in bars.values()):
        pytest.skip("fx_4h.duckdb is missing one or more required symbols")

    passing = apply_universe_filter(bars, UniverseFilterConfig(enabled=True))

    assert "EUR_USD" in passing
    assert {"USD_HUF", "USD_CZK", "USD_TRY", "USD_ZAR"}.isdisjoint(passing)
