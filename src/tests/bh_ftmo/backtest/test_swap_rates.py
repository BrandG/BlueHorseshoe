"""Tests for swap-rate cache and OANDA financing parsing."""

from __future__ import annotations

# pylint: disable=missing-function-docstring
import json
from datetime import date

import pytest

from bh_ftmo.backtest.swap import SwapRates
from bh_ftmo.backtest.swap_rates import fetch_oanda_financing_rates, fetch_or_load_cached


def test_fetch_or_load_cached_uses_cache_when_present(tmp_path):
    today = date(2026, 4, 25)
    cache_path = tmp_path / f"swap_rates_{today.isoformat()}.json"
    cache_path.write_text(
        json.dumps({"EUR_USD": {"long_rate": -3.1, "short_rate": 1.2}}, sort_keys=True),
        encoding="utf-8",
    )

    class _Client:
        def list_instruments(self):
            raise AssertionError("cache hit should avoid OANDA call")

    rates = fetch_or_load_cached(_Client(), today, cache_dir=tmp_path)
    assert rates == {"EUR_USD": SwapRates(-3.1, 1.2)}


def test_fetch_or_load_cached_writes_cache_on_miss(tmp_path):
    today = date(2026, 4, 25)

    class _Client:
        def list_instruments(self):
            return {"EUR_USD": {"name": "EUR_USD", "financing": {"longRate": "-2.5", "shortRate": "1.5"}}}

    rates = fetch_or_load_cached(_Client(), today, cache_dir=tmp_path)
    assert rates == {"EUR_USD": SwapRates(-2.5, 1.5)}
    payload = json.loads((tmp_path / f"swap_rates_{today.isoformat()}.json").read_text(encoding="utf-8"))
    assert payload == {"EUR_USD": {"long_rate": -2.5, "short_rate": 1.5}}


def test_fetch_or_load_cached_no_swap_returns_empty_dict_without_client(tmp_path):
    assert fetch_or_load_cached(None, date(2026, 4, 25), cache_dir=tmp_path, no_swap=True) == {}


def test_fetch_or_load_cached_raises_when_client_none_and_cache_miss(tmp_path):
    with pytest.raises(ValueError, match="OANDA client is required"):
        fetch_or_load_cached(None, date(2026, 4, 25), cache_dir=tmp_path)


def test_oanda_response_parsed_correctly():
    class _Client:
        def list_instruments(self):
            return {
                "EUR_USD": {"name": "EUR_USD", "financing": {"longRate": "-3.125", "shortRate": "1.875"}},
                "USD_JPY": {"name": "USD_JPY", "financing": {"longRate": "2.500", "shortRate": "-4.500"}},
                "XAU_USD": {"name": "XAU_USD"},
            }

    assert fetch_oanda_financing_rates(_Client()) == {
        "EUR_USD": SwapRates(-3.125, 1.875),
        "USD_JPY": SwapRates(2.5, -4.5),
    }
