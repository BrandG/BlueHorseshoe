"""Tests for bh_ftmo.indicators.dxy_correlation."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bh_ftmo.indicators import (
    DXY_BASE_CONSTANT,
    DXY_WEIGHTS,
    dxy_correlation,
    synthesize_dxy,
    usd_pair_correlations,
)


def _constant_pairs(n: int = 30) -> dict[str, pd.DataFrame]:
    """Return all 6 DXY constituents held at a fixed price for n bars."""
    # Representative 2026-ish FX prices
    prices = {
        "EUR_USD": 1.10,
        "USD_JPY": 150.0,
        "GBP_USD": 1.30,
        "USD_CAD": 1.35,
        "USD_SEK": 10.0,
        "USD_CHF": 0.88,
    }
    return {sym: pd.DataFrame({"close": [p] * n}) for sym, p in prices.items()}


# ---- synthesize_dxy ---------------------------------------------------


def test_synthesize_dxy_returns_a_series():
    pairs = _constant_pairs(10)
    dxy = synthesize_dxy(pairs)
    assert isinstance(dxy, pd.Series)
    assert len(dxy) == 10


def test_synthesize_dxy_formula_hand_check():
    """DXY with fixed prices should equal the closed-form product."""
    pairs = _constant_pairs(5)
    dxy = synthesize_dxy(pairs)
    # Manual computation
    expected = DXY_BASE_CONSTANT
    for sym, w in DXY_WEIGHTS.items():
        price = pairs[sym]["close"].iloc[0]
        expected *= price ** w
    assert dxy.iloc[0] == pytest.approx(expected)


def test_synthesize_dxy_missing_constituent_raises():
    pairs = _constant_pairs(5)
    del pairs["EUR_USD"]
    with pytest.raises(ValueError, match="missing"):
        synthesize_dxy(pairs)


def test_synthesize_dxy_uses_intersection_index():
    """If one pair is shorter, the output uses the intersection."""
    pairs = _constant_pairs(30)
    pairs["USD_JPY"] = pairs["USD_JPY"].iloc[:20]
    dxy = synthesize_dxy(pairs)
    assert len(dxy) == 20


def test_synthesize_dxy_accepts_bid_ask_dataframe():
    df_template = {
        "close_bid": [1.10, 1.11],
        "close_ask": [1.101, 1.111],
    }
    pairs = {
        "EUR_USD": pd.DataFrame({"close_bid": [1.10, 1.11], "close_ask": [1.101, 1.111]}),
        "USD_JPY": pd.DataFrame({"close_bid": [150.0, 150.5], "close_ask": [150.01, 150.51]}),
        "GBP_USD": pd.DataFrame({"close_bid": [1.30, 1.30], "close_ask": [1.301, 1.301]}),
        "USD_CAD": pd.DataFrame({"close_bid": [1.35, 1.35], "close_ask": [1.351, 1.351]}),
        "USD_SEK": pd.DataFrame({"close_bid": [10.0, 10.0], "close_ask": [10.01, 10.01]}),
        "USD_CHF": pd.DataFrame({"close_bid": [0.88, 0.88], "close_ask": [0.881, 0.881]}),
    }
    dxy = synthesize_dxy(pairs)
    assert len(dxy) == 2
    assert not dxy.isna().any()


def test_synthesize_dxy_moves_up_when_usd_strengthens():
    """If every USD pair shifts in the USD-strengthening direction, DXY rises."""
    n = 5
    # Bar 0: baseline; bar 1+: USD up 1% against every other currency
    pairs = {
        "EUR_USD": pd.DataFrame({"close": [1.10, 1.089, 1.089, 1.089, 1.089]}),  # EUR down
        "GBP_USD": pd.DataFrame({"close": [1.30, 1.287, 1.287, 1.287, 1.287]}),  # GBP down
        "USD_JPY": pd.DataFrame({"close": [150.0, 151.5, 151.5, 151.5, 151.5]}), # USD up
        "USD_CAD": pd.DataFrame({"close": [1.35, 1.3635, 1.3635, 1.3635, 1.3635]}),
        "USD_SEK": pd.DataFrame({"close": [10.0, 10.1, 10.1, 10.1, 10.1]}),
        "USD_CHF": pd.DataFrame({"close": [0.88, 0.8888, 0.8888, 0.8888, 0.8888]}),
    }
    dxy = synthesize_dxy(pairs)
    assert dxy.iloc[1] > dxy.iloc[0]


# ---- dxy_correlation ---------------------------------------------------


def _rw_log_prices(n: int, *, seed: int) -> pd.Series:
    """Random-walk prices (start at 100)."""
    rng = np.random.default_rng(seed)
    returns = rng.normal(0, 0.001, n)
    return pd.Series(100 * np.exp(returns.cumsum()))


def test_dxy_correlation_window_validation():
    dxy = pd.Series([100, 101, 102])
    pair = pd.Series([1.1, 1.09, 1.08])
    with pytest.raises(ValueError, match="window"):
        dxy_correlation(pair, dxy, window=1)


def test_dxy_correlation_identical_series_is_one():
    """A series perfectly correlated with itself → corr = 1."""
    s = _rw_log_prices(50, seed=1)
    out = dxy_correlation(s, s, window=20).dropna()
    assert (out > 0.999).all()


def test_dxy_correlation_negated_series_is_minus_one():
    """Inversely correlated series (log-ratio flipped) → corr ≈ -1."""
    s = _rw_log_prices(50, seed=2)
    inverse = 1 / s  # log(1/s) = -log(s), so log-returns are exactly negated
    out = dxy_correlation(s, inverse, window=20).dropna()
    assert (out < -0.999).all()


def test_dxy_correlation_usd_base_pair_positively_correlated():
    """USD_JPY returns are scaled from DXY returns → positive correlation."""
    n = 100
    rng = np.random.default_rng(3)
    usd_drift = rng.normal(0, 0.001, n).cumsum()  # USD strength series
    noise = rng.normal(0, 0.0003, n).cumsum()
    # DXY rises with USD strength
    dxy = pd.Series(100 * np.exp(usd_drift))
    # USD_JPY rises with USD strength (USD is base) + some noise
    usd_jpy = pd.Series(150 * np.exp(usd_drift + noise))
    corr = dxy_correlation(usd_jpy, dxy, window=30).dropna()
    assert corr.mean() > 0.5


def test_dxy_correlation_usd_quote_pair_negatively_correlated():
    """EUR_USD returns should be negatively correlated with DXY."""
    n = 100
    rng = np.random.default_rng(4)
    usd_drift = rng.normal(0, 0.001, n).cumsum()
    noise = rng.normal(0, 0.0003, n).cumsum()
    dxy = pd.Series(100 * np.exp(usd_drift))
    # EUR_USD falls when USD strengthens
    eur_usd = pd.Series(1.10 * np.exp(-usd_drift + noise))
    corr = dxy_correlation(eur_usd, dxy, window=30).dropna()
    assert corr.mean() < -0.5


# ---- usd_pair_correlations --------------------------------------------


def test_usd_pair_correlations_filters_non_usd_pairs():
    # EUR_GBP is a cross — should not appear in output
    pairs = {
        "EUR_USD": pd.DataFrame({"close": _rw_log_prices(50, seed=10).tolist()}),
        "EUR_GBP": pd.DataFrame({"close": _rw_log_prices(50, seed=11).tolist()}),
    }
    dxy = _rw_log_prices(50, seed=12)
    df = usd_pair_correlations(pairs, dxy, window=20)
    assert "EUR_USD" in df.columns
    assert "EUR_GBP" not in df.columns


def test_usd_pair_correlations_respects_explicit_symbol_filter():
    pairs = {
        "EUR_USD": pd.DataFrame({"close": _rw_log_prices(30, seed=13).tolist()}),
        "USD_JPY": pd.DataFrame({"close": _rw_log_prices(30, seed=14).tolist()}),
    }
    dxy = _rw_log_prices(30, seed=15)
    df = usd_pair_correlations(pairs, dxy, window=10, symbols=["EUR_USD"])
    assert set(df.columns) == {"EUR_USD"}


# ---- integration with real FxStore data -------------------------------


def test_dxy_correlation_on_real_fx_data():
    from bh_ftmo.data.fx_store import FxStore

    store = FxStore(read_only=True)
    try:
        pairs = {}
        for sym in DXY_WEIGHTS:
            df = store.load(sym, granularity="H4",
                            start=pd.Timestamp("2025-06-01").to_pydatetime(),
                            end=pd.Timestamp("2025-09-01").to_pydatetime())
            if len(df) > 0:
                pairs[sym] = df
    finally:
        store.close()

    missing = set(DXY_WEIGHTS) - set(pairs)
    if missing:
        pytest.skip(f"missing DXY constituent data: {missing}")

    dxy = synthesize_dxy(pairs)
    # DXY of 2025 should be somewhere plausible (75-150 range is generous)
    assert (dxy > 50).all()
    assert (dxy < 200).all()

    from bh_ftmo.indicators.strength import _close_series

    # USD_JPY should show POSITIVE correlation with DXY (USD is base)
    corr_jpy = dxy_correlation(_close_series(pairs["USD_JPY"]), dxy, window=60).dropna()
    assert corr_jpy.mean() > 0.2, f"USD_JPY corr with DXY was {corr_jpy.mean():.3f}"

    # EUR_USD should show NEGATIVE correlation with DXY (USD is quote)
    corr_eur = dxy_correlation(_close_series(pairs["EUR_USD"]), dxy, window=60).dropna()
    assert corr_eur.mean() < -0.2, f"EUR_USD corr with DXY was {corr_eur.mean():.3f}"
