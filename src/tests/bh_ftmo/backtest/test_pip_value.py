"""Unit tests for FX pip-value mechanics and quote-currency conversion."""

from __future__ import annotations

# pylint: disable=missing-function-docstring

import json
from pathlib import Path

import pytest

from bh_ftmo.backtest.pip_value import pip_value_in_account_ccy, quote_to_account_rate
from bh_ftmo.backtest.types import PairSpec

REPO_ROOT = Path(__file__).resolve().parents[4]
LITE_CONFIG_PATH = REPO_ROOT / "src" / "bh_lite_config.json"



def _expected_value(ftmo_symbol: str) -> float:
    config = json.loads(LITE_CONFIG_PATH.read_text(encoding="utf-8"))
    for item in config["instruments"]:
        if item["ftmo"] == ftmo_symbol:
            return float(item["dollar_per_pip_per_lot"])
    raise AssertionError(f"missing config entry for {ftmo_symbol}")



def test_pip_value_in_account_currency_uses_quote_conversion():
    pair = PairSpec(symbol="EUR_GBP", pip_size=0.0001, contract_size=100_000)
    assert pip_value_in_account_ccy(pair, "USD", quote_to_account_rate=1.25) == pytest.approx(12.5)



def test_quote_to_account_rate_direct_quote_currency_match():
    assert quote_to_account_rate("EUR_USD", "USD", {"EUR_USD": 1.10}) == pytest.approx(1.0)



def test_quote_to_account_rate_inverts_usd_base_pair():
    rate = quote_to_account_rate("USD_JPY", "USD", {"USD_JPY": 150.0})
    assert rate == pytest.approx(1.0 / 150.0)



def test_quote_to_account_rate_resolves_cross_via_graph():
    rate = quote_to_account_rate(
        "AUD_NZD",
        "USD",
        {
            "AUD_NZD": 1.0800,
            "NZD_USD": 0.6000,
        },
    )
    assert rate == pytest.approx(0.6000)



def test_quote_to_account_rate_raises_without_path():
    with pytest.raises(ValueError, match="no quote-to-account conversion path"):
        quote_to_account_rate("EUR_GBP", "USD", {"EUR_CHF": 0.95})



@pytest.mark.parametrize(
    ("pair", "pip_size", "rates", "expected", "known_deviation"),
    [
        ("EUR_USD", 0.0001, {"EUR_USD": 1.0820}, 10.0, False),
        ("GBP_USD", 0.0001, {"GBP_USD": 1.2710}, 10.0, False),
        ("USD_JPY", 0.01, {"USD_JPY": 150.00}, 6.67, False),
        ("USD_CAD", 0.0001, {"USD_CAD": 1.3333}, 7.50, False),
        ("EUR_GBP", 0.0001, {"EUR_GBP": 0.8560, "GBP_USD": 1.2500}, 12.50, False),
        ("EUR_JPY", 0.01, {"EUR_JPY": 162.50, "USD_JPY": 150.00}, 6.67, False),
        ("AUD_NZD", 0.0001, {"AUD_NZD": 1.0800, "NZD_USD": 0.6000}, 6.00, False),
        ("USD_HUF", 0.01, {"USD_HUF": 370.00}, 0.27, True),
    ],
)
def test_ftmo_spec_cross_check_against_bh_lite_values(pair, pip_size, rates, expected, known_deviation):
    """Cross-check sample pip values against BH Lite FTMO-spec fixtures within tolerance.

    The ``USD_HUF`` fixture is intentionally marked as a known deviation because
    BH Lite's historical exotic-pair sizing carried the documented 10x error.
    The implementation stays mathematically correct and leaves that discrepancy
    visible for Brand to verify against FTMO's own pip-value page.
    """

    pair_spec = PairSpec(symbol=pair, pip_size=pip_size, contract_size=100_000)
    rate = quote_to_account_rate(pair, "USD", rates)
    got = pip_value_in_account_ccy(pair_spec, "USD", rate)
    config_expected = _expected_value(pair.replace("_", "") + ".sim")
    assert config_expected == pytest.approx(expected, rel=0.0001)
    if known_deviation:
        assert got != pytest.approx(config_expected, rel=0.05)
        assert got == pytest.approx(2.70, rel=0.05)
    else:
        assert got == pytest.approx(config_expected, rel=0.05)
