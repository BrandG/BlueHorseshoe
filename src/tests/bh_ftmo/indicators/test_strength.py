"""Validate currency strength helpers and hand-computed strength scenarios."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bh_ftmo.indicators.strength import (
    _close_series,
    _split_pair,
    currency_strength,
    rank_currency_strength,
)


class TestSplitPair:
    @pytest.mark.parametrize(
        ("symbol", "expected"),
        [
            ("EUR_USD", ("EUR", "USD")),
            ("eur_usd", ("EUR", "USD")),
            ("INVALID", None),
            ("EUR_USD_X", None),
            ("EU_USD", None),
        ],
    )
    def test_splits_only_two_three_letter_legs(
        self,
        symbol: str,
        expected: tuple[str, str] | None,
    ) -> None:
        assert _split_pair(symbol) == expected


class TestCloseSeries:
    def test_returns_close_column_when_present(self) -> None:
        df = pd.DataFrame({"close": [1.0, 1.1, 1.2]})

        pd.testing.assert_series_equal(_close_series(df), df["close"])

    def test_returns_bid_ask_mid_when_close_is_absent(self) -> None:
        df = pd.DataFrame(
            {"close_bid": [1.00, 1.10], "close_ask": [1.02, 1.12]},
            index=pd.Index(["a", "b"]),
        )
        expected = pd.Series([1.01, 1.11], index=df.index)

        pd.testing.assert_series_equal(_close_series(df), expected)

    def test_raises_when_no_supported_close_columns_exist(self) -> None:
        with pytest.raises(ValueError, match="must contain 'close'"):
            _close_series(pd.DataFrame({"open": [1.0]}))


class TestCurrencyStrength:
    def test_three_pair_log_return_scenario_matches_hand_computation(self) -> None:
        index = pd.date_range("2024-01-01", periods=5, freq="4h")
        pairs = {
            "EUR_USD": pd.DataFrame(
                {"close": np.exp([0.0, 0.0, 0.0, 0.0, 0.010])},
                index=index,
            ),
            "EUR_JPY": pd.DataFrame(
                {"close": np.exp([0.0, 0.0, 0.0, 0.0, 0.020])},
                index=index,
            ),
            "USD_JPY": pd.DataFrame(
                {"close": np.exp([0.0, 0.0, 0.0, 0.0, 0.005])},
                index=index,
            ),
        }
        expected = pd.DataFrame(
            {
                "EUR": [np.nan, np.nan, np.nan, np.nan, 0.0150],
                "USD": [np.nan, np.nan, np.nan, np.nan, -0.0025],
                "JPY": [np.nan, np.nan, np.nan, np.nan, -0.0125],
            },
            index=index,
        )

        result = currency_strength(
            pairs,
            lookback=4,
            currencies=("EUR", "USD", "JPY"),
        )

        pd.testing.assert_frame_equal(result, expected, rtol=1e-12, atol=1e-12)

    def test_currency_without_contributing_pair_is_all_nan(self) -> None:
        pairs = {
            "EUR_USD": pd.DataFrame(
                {"close": np.exp([0.0, 0.0, 0.010])},
                index=pd.RangeIndex(3),
            )
        }

        result = currency_strength(
            pairs,
            lookback=2,
            currencies=("EUR", "CHF"),
        )

        assert result["EUR"].iloc[-1] == pytest.approx(0.010)
        assert result["CHF"].isna().all()

    def test_invalid_pair_symbol_is_silently_skipped(self) -> None:
        pairs = {
            "EUR_USD": pd.DataFrame(
                {"close": np.exp([0.0, 0.0, 0.010])},
                index=pd.RangeIndex(3),
            ),
            "BTCC_USD": pd.DataFrame(
                {"close": np.exp([0.0, 0.0, 1.000])},
                index=pd.RangeIndex(3),
            ),
        }

        result = currency_strength(
            pairs,
            lookback=2,
            currencies=("EUR", "USD"),
        )

        assert result["EUR"].iloc[-1] == pytest.approx(0.010)
        assert result["USD"].iloc[-1] == pytest.approx(-0.010)

    def test_rejects_empty_pairs(self) -> None:
        with pytest.raises(ValueError, match="pairs is empty"):
            currency_strength({}, lookback=2)

    def test_rejects_lookback_less_than_one(self) -> None:
        pairs = {"EUR_USD": pd.DataFrame({"close": [1.0, 1.1]})}

        with pytest.raises(ValueError, match="lookback must be >= 1"):
            currency_strength(pairs, lookback=0)


class TestRankCurrencyStrength:
    def test_ranks_weakest_to_strongest_and_preserves_all_nan_rows(self) -> None:
        strength = pd.DataFrame(
            {
                "EUR": [0.015, np.nan],
                "USD": [-0.0025, np.nan],
                "JPY": [-0.0125, np.nan],
            },
            index=["signal", "empty"],
        )
        expected = pd.DataFrame(
            {
                "EUR": [3.0, np.nan],
                "USD": [2.0, np.nan],
                "JPY": [1.0, np.nan],
            },
            index=strength.index,
        )

        pd.testing.assert_frame_equal(rank_currency_strength(strength), expected)
