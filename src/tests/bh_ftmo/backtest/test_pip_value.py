"""Unit tests for FX pip-value mechanics and quote-currency conversion."""

from __future__ import annotations

# pylint: disable=missing-function-docstring

import json
from pathlib import Path

import pytest

from bh_ftmo.backtest.pip_value import pip_value_in_account_ccy, quote_to_account_rate
from bh_ftmo.backtest.types import PairSpec

REPO_ROOT = Path(__file__).resolve().parents[4]
LITE_CONFIG_PATH = REPO_ROOT / "src" / "bud" / "config.json"



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


def test_quote_to_account_rate_supports_configured_usd_commodity():
    assert quote_to_account_rate("XAU_USD", "USD", {"XAU_USD": 2350.0}) == pytest.approx(1.0)


def test_pip_value_uses_explicit_commodity_dollars_per_pip():
    pair = PairSpec(
        symbol="XAU_USD",
        pip_size=0.01,
        contract_size=100,
        instrument_type="commodity",
        dollar_per_pip_per_lot=1.0,
    )
    assert pip_value_in_account_ccy(pair, "USD", quote_to_account_rate=1.0) == pytest.approx(1.0)



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



# Approximate value of one unit of each quote currency in USD. Only ever used
# as an order-of-magnitude reference, so the band below is deliberately wide:
# this test must NOT pin config.json to a point-in-time value, because
# `size.py --refresh-config` legitimately rewrites those values from live
# rates. What it must catch is a row wrong by a FACTOR — the failure that
# actually loses money.
_QUOTE_TO_USD = {
    "USD": 1.0,
    "JPY": 1 / 150.0,
    "CAD": 1 / 1.33,
    "GBP": 1.27,
    "NZD": 0.60,
    "HUF": 1 / 340.0,
}
_BAND = 0.35   # tolerates years of drift; still catches a 10x slip

# (pair, pip_size) samples spanning USD-quoted, JPY-quoted, crosses and exotics.
_SAMPLES = [
    ("EUR_USD", 0.0001), ("GBP_USD", 0.0001), ("USD_JPY", 0.01),
    ("USD_CAD", 0.0001), ("EUR_GBP", 0.0001), ("EUR_JPY", 0.01),
    ("AUD_NZD", 0.0001), ("USD_HUF", 0.01),
]


@pytest.mark.parametrize(("pair", "pip_size"), _SAMPLES)
def test_config_dollar_per_pip_is_plausible_for_its_quote_currency(pair, pip_size):
    """Each config row must satisfy dpp == pip_size * contract_size * quote->USD.

    That identity is what makes a row correct, so checking it is the cheapest
    possible guard on the table — and it is the guard that was missing.
    EURHUF/USDHUF carried dpp 0.27 against pip_size 0.01, which implies
    USD/HUF ~ 3,704 when it was ~314. That 11.8x error sized real positions at
    13x their intended risk in May 2026 (fixed 2026-08-14, commit 1bf9dad).

    Deliberately a band, not an equality: --refresh-config rewrites these from
    live rates, so pinning them would make a supported workflow fail the suite.
    A factor-of-ten error cannot hide inside 35%.
    """
    ftmo_symbol = pair.replace("_", "") + ".sim"
    config_dpp = _expected_value(ftmo_symbol)
    quote_ccy = pair.split("_")[1]
    expected_dpp = pip_size * 100_000 * _QUOTE_TO_USD[quote_ccy]

    assert config_dpp == pytest.approx(expected_dpp, rel=_BAND), (
        f"{ftmo_symbol}: config says ${config_dpp}/pip/lot, but pip_size "
        f"{pip_size} x 100,000 x ({quote_ccy}->USD ~{_QUOTE_TO_USD[quote_ccy]:.4g}) "
        f"= ${expected_dpp:.4g}. This is the HUF failure mode — a row wrong by "
        f"a factor sizes positions by that same factor."
    )


def test_pip_value_matches_config_for_a_sampled_pair():
    """The computed pip value and the config row agree at the same spot rate."""
    spec = PairSpec(symbol="USD_CAD", pip_size=0.0001, contract_size=100_000)
    config_dpp = _expected_value("USDCAD.sim")
    implied_spot = 0.0001 * 100_000 / config_dpp
    rate = quote_to_account_rate("USD_CAD", "USD", {"USD_CAD": implied_spot})
    assert pip_value_in_account_ccy(spec, "USD", rate) == pytest.approx(config_dpp, rel=1e-6)
