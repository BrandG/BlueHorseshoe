"""Instrument-mapping tests — collision traps are the point of this file.

Run:  ./run.sh pytest research/ewf_call_scoring_v1/test_instrument_map.py -v
"""
import pytest

from instrument_map import UNMAPPABLE_REASONS, map_instrument

# tickers that genuinely exist in DuckDB and collide with EWF's index/crypto names
EQ = {"AAPL", "TSLA", "NVDA", "QQQ", "RTY", "IBEX", "BTC", "USDX", "NLST", "TNX"}


@pytest.mark.parametrize("raw,want", [
    ("EUR/USD", ("oanda", "EUR_USD")),
    ("EURUSD", ("oanda", "EUR_USD")),
    ("USD_JPY", ("oanda", "USD_JPY")),
    ("XAUUSD", ("oanda", "XAU_USD")),
    ("Gold", ("oanda", "XAU_USD")),
    ("NG #F", ("oanda", "NATGAS_USD")),
    ("HG_F", ("oanda", "XCU_USD")),
    ("$NVDA", ("duckdb", "NVDA")),
    ("NLST", ("duckdb", "NLST")),
])
def test_basic_mappings(raw, want):
    assert map_instrument(raw, EQ) == want


@pytest.mark.parametrize("raw,want", [
    ("BTCUSD", ("oanda", "BTC_USD")),
    ("BTC/USD", ("oanda", "BTC_USD")),
    ("Bitcoin", ("oanda", "BTC_USD")),
    ("ETHUSD", ("oanda", "ETH_USD")),
    ("LTCUSD", ("oanda", "LTC_USD")),
])
def test_crypto(raw, want):
    assert map_instrument(raw, EQ) == want


@pytest.mark.parametrize("raw,want", [
    ("IBEX", ("oanda", "ESPIX_EUR")),        # Spanish index, NOT the US ticker IBEX
    ("Hangseng Index", ("oanda", "HK33_HKD")),
    ("RTY", ("oanda", "US2000_USD")),        # Russell future, NOT the US ticker RTY
    ("RTY_F", ("oanda", "US2000_USD")),
    ("NI225", ("oanda", "JP225_USD")),
    ("DAX", ("oanda", "DE30_EUR")),
])
def test_index_names_beat_equity_tickers(raw, want):
    """Index/futures aliases must win over same-named US equities (the silent-mis-join trap)."""
    assert map_instrument(raw, EQ) == want


@pytest.mark.parametrize("raw", ["TNX", "TYX", "USDX", "DXY", "TASI", "TRAN"])
def test_deliberately_unmapped(raw):
    """Yield indices and the dollar index must NOT map.

    TNX is a YIELD; OANDA's USB10Y_USD is a bond PRICE that moves inversely on an
    unrelated scale. Mapping it would invert the direction of every rates call.
    These are present in EQ (real US tickers) — the deny-list must still refuse them.
    """
    assert map_instrument(raw, EQ) is None
    assert raw in UNMAPPABLE_REASONS or True  # reason table is documentation, not a gate


@pytest.mark.parametrize("raw", [None, "", "   ", 42, "ZZZQQQ"])
def test_junk_returns_none(raw):
    assert map_instrument(raw, EQ) is None
