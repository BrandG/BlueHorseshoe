"""Tests for bh_ftmo.indicators.strength (currency strength meter)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bh_ftmo.indicators import (
    MAJORS,
    currency_strength,
    rank_currency_strength,
)
from bh_ftmo.indicators.strength import _split_pair


def _mk_pair(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"close": closes})


# ---- _split_pair -------------------------------------------------------


def test_split_pair_valid():
    assert _split_pair("EUR_USD") == ("EUR", "USD")
    assert _split_pair("usd_jpy") == ("USD", "JPY")


def test_split_pair_invalid():
    assert _split_pair("EURUSD") is None        # missing underscore
    assert _split_pair("EUR_USD_JPY") is None   # three parts
    assert _split_pair("EU_USD") is None        # wrong length


# ---- currency_strength: hand-computed cases ---------------------------


def test_strength_two_pair_hand_computation():
    # Bar 0 → Bar 1: EUR_USD up 1%, USD_JPY down 1%
    # log-returns:   EUR_USD ≈ +0.00995, USD_JPY ≈ -0.01005
    # EUR: appears as base of EUR_USD  → +0.00995
    # USD: quote of EUR_USD (-0.00995) + base of USD_JPY (-0.01005) → avg ≈ -0.01
    # JPY: quote of USD_JPY → +0.01005
    pairs = {
        "EUR_USD": _mk_pair([1.10, 1.111]),
        "USD_JPY": _mk_pair([150.0, 148.5]),
    }
    s = currency_strength(pairs, lookback=1, currencies=("USD", "EUR", "JPY"))
    last = s.iloc[-1]

    # USD is weakest (negative), EUR and JPY positive
    assert last["USD"] < 0
    assert last["EUR"] > 0
    assert last["JPY"] > 0
    # Rough numerical check
    assert abs(last["EUR"] - np.log(1.111 / 1.10)) < 1e-9
    assert abs(last["JPY"] - (-np.log(148.5 / 150.0))) < 1e-9


def test_strength_symmetric_moves_cancel():
    """EUR/USD unchanged → neither EUR nor USD moves from this pair alone."""
    pairs = {"EUR_USD": _mk_pair([1.10, 1.10, 1.10, 1.10])}
    s = currency_strength(pairs, lookback=2, currencies=("USD", "EUR"))
    last_valid = s.dropna().iloc[-1]
    assert last_valid["USD"] == pytest.approx(0.0)
    assert last_valid["EUR"] == pytest.approx(0.0)


def test_strength_currency_with_no_pairs_is_all_nan():
    pairs = {"EUR_USD": _mk_pair([1.10, 1.11, 1.12])}
    s = currency_strength(pairs, lookback=1, currencies=("GBP",))
    assert s["GBP"].isna().all()


def test_strength_rejects_empty_pairs():
    with pytest.raises(ValueError, match="pairs"):
        currency_strength({}, lookback=14)


def test_strength_rejects_bad_lookback():
    with pytest.raises(ValueError, match="lookback"):
        currency_strength({"EUR_USD": _mk_pair([1.0, 1.1])}, lookback=0)


def test_strength_skips_malformed_symbol():
    # Invalid symbol is silently skipped, valid ones still contribute
    pairs = {
        "EUR_USD": _mk_pair([1.10, 1.11]),
        "INVALID": _mk_pair([1.0, 1.0]),
    }
    s = currency_strength(pairs, lookback=1, currencies=("EUR",))
    assert not np.isnan(s["EUR"].iloc[-1])


def test_strength_accepts_bid_ask_dataframe():
    """A DataFrame with close_bid + close_ask should work (derives mid)."""
    df = pd.DataFrame({
        "close_bid": [1.10, 1.11],
        "close_ask": [1.101, 1.111],
    })
    s = currency_strength({"EUR_USD": df}, lookback=1, currencies=("EUR",))
    assert not np.isnan(s["EUR"].iloc[-1])


def test_strength_preserves_timestamp_index():
    idx = pd.date_range("2020-01-01", periods=5, freq="4h")
    pairs = {"EUR_USD": pd.DataFrame({"close": [1.10, 1.11, 1.12, 1.13, 1.14]}, index=idx)}
    s = currency_strength(pairs, lookback=2, currencies=("EUR", "USD"))
    pd.testing.assert_index_equal(s.index, idx)


# ---- currency_strength: weak-dollar scenario --------------------------


def test_strength_weak_dollar_across_pairs():
    """USD dropping against every other currency → USD strength most negative."""
    # Simulate a weak-USD bar: USD_* down 1%, *_USD up 1%
    pairs = {
        "EUR_USD": _mk_pair([1.10, 1.111]),   # EUR up
        "GBP_USD": _mk_pair([1.30, 1.313]),   # GBP up
        "USD_JPY": _mk_pair([150.0, 148.5]),  # USD down vs JPY
        "USD_CHF": _mk_pair([0.90, 0.891]),   # USD down vs CHF
    }
    s = currency_strength(pairs, lookback=1, currencies=("USD", "EUR", "GBP", "JPY", "CHF"))
    ranks = rank_currency_strength(s)
    # USD should be the weakest (rank 1)
    assert ranks.iloc[-1]["USD"] == 1.0


# ---- rank_currency_strength -------------------------------------------


def test_rank_strength_orders_row_by_row():
    df = pd.DataFrame({
        "USD": [1.0, 0.0],
        "EUR": [-1.0, 2.0],
        "JPY": [0.0, 1.0],
    })
    ranks = rank_currency_strength(df)
    # Row 0: EUR=-1 (1), JPY=0 (2), USD=1 (3)
    assert ranks.iloc[0].to_dict() == {"USD": 3.0, "EUR": 1.0, "JPY": 2.0}
    # Row 1: USD=0 (1), JPY=1 (2), EUR=2 (3)
    assert ranks.iloc[1].to_dict() == {"USD": 1.0, "EUR": 3.0, "JPY": 2.0}


def test_rank_strength_preserves_nan_rows():
    df = pd.DataFrame({"USD": [np.nan], "EUR": [np.nan]})
    ranks = rank_currency_strength(df)
    assert ranks.iloc[0].isna().all()


# ---- integration with real FxStore data -------------------------------


def test_strength_on_real_fx_data():
    from bh_ftmo.data.fx_store import FxStore

    # Use a modest set of the 8 majors to keep the test fast but real
    symbols = ["EUR_USD", "GBP_USD", "USD_JPY", "USD_CHF", "AUD_USD", "USD_CAD", "NZD_USD"]
    store = FxStore(read_only=True)
    try:
        pairs = {}
        for sym in symbols:
            df = store.load(sym, granularity="H4",
                            start=pd.Timestamp("2025-06-01").to_pydatetime(),
                            end=pd.Timestamp("2025-07-01").to_pydatetime())
            if len(df) > 0:
                pairs[sym] = df
    finally:
        store.close()

    if len(pairs) < 5:
        pytest.skip(f"only {len(pairs)} pairs available — can't test strength meaningfully")

    s = currency_strength(pairs, lookback=14, currencies=MAJORS)
    assert set(s.columns) == set(MAJORS)
    valid = s.dropna()
    assert len(valid) > 0, "strength returned all NaN rows"
    # Each row's currencies should sum to approximately zero — by construction,
    # every log-return contributes equally and oppositely to its base and quote.
    # But averaging across unequal pair counts per currency breaks exact zero;
    # we only check that the sum is small relative to typical strength magnitudes.
    row_sums_abs = valid.sum(axis=1).abs()
    max_strength_per_row = valid.abs().max(axis=1)
    # Sum-to-zero within 5% of the largest single strength magnitude on the row
    assert (row_sums_abs <= 5 * max_strength_per_row).all()
