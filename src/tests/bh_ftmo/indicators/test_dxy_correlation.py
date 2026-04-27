"""Validate synthesized DXY and rolling pair correlation helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bh_ftmo.indicators.dxy_correlation import (
    DXY_BASE_CONSTANT,
    DXY_WEIGHTS,
    dxy_correlation,
    synthesize_dxy,
    usd_pair_correlations,
)


def _dxy_pairs(
    *,
    index: pd.Index | None = None,
    overrides: dict[str, pd.DataFrame] | None = None,
) -> dict[str, pd.DataFrame]:
    index = index if index is not None else pd.RangeIndex(3)
    pairs = {
        sym: pd.DataFrame({"close": np.ones(len(index), dtype=float)}, index=index)
        for sym in DXY_WEIGHTS
    }
    if overrides:
        pairs.update(overrides)
    return pairs


class TestSynthesizeDxy:
    def test_identity_case_returns_base_constant(self) -> None:
        result = synthesize_dxy(_dxy_pairs())
        expected = pd.Series(
            [DXY_BASE_CONSTANT] * 3,
            index=pd.RangeIndex(3),
            name="dxy",
        )

        pd.testing.assert_series_equal(result, expected)

    def test_negative_eurusd_weight_decreases_dxy_when_eurusd_rises(self) -> None:
        pairs = _dxy_pairs(
            overrides={
                "EUR_USD": pd.DataFrame({"close": [1.0, 1.01]}, index=pd.RangeIndex(2))
            }
        )
        expected_value = DXY_BASE_CONSTANT * np.exp(
            DXY_WEIGHTS["EUR_USD"] * np.log(1.01)
        )

        result = synthesize_dxy(pairs)

        assert result.iloc[0] == pytest.approx(DXY_BASE_CONSTANT)
        assert result.iloc[1] == pytest.approx(expected_value)
        assert result.iloc[1] < result.iloc[0]

    def test_positive_usdjpy_weight_increases_dxy_when_usdjpy_rises(self) -> None:
        pairs = _dxy_pairs(
            overrides={
                "USD_JPY": pd.DataFrame({"close": [1.0, 1.01]}, index=pd.RangeIndex(2))
            }
        )
        expected_value = DXY_BASE_CONSTANT * np.exp(
            DXY_WEIGHTS["USD_JPY"] * np.log(1.01)
        )

        result = synthesize_dxy(pairs)

        assert result.iloc[1] == pytest.approx(expected_value)
        assert result.iloc[1] > result.iloc[0]

    def test_raises_when_required_constituent_is_missing(self) -> None:
        with pytest.raises(ValueError, match="missing constituent pairs"):
            synthesize_dxy({})

    def test_aligns_result_to_constituent_index_intersection(self) -> None:
        full_index = pd.Index([0, 1, 2, 3])
        pairs = _dxy_pairs(index=full_index)
        pairs["EUR_USD"] = pd.DataFrame({"close": [1.0, 1.0, 1.0]}, index=[0, 1, 2])
        pairs["USD_JPY"] = pd.DataFrame({"close": [1.0, 1.0, 1.0]}, index=[1, 2, 3])

        result = synthesize_dxy(pairs)

        assert result.index.tolist() == [1, 2]


class TestDxyCorrelation:
    def test_perfect_positive_log_return_correlation(self) -> None:
        index = pd.RangeIndex(50)
        pair_close = pd.Series(np.linspace(1.0, 1.10, 50), index=index)
        dxy = 2 * pair_close

        corr = dxy_correlation(pair_close, dxy, window=20)

        assert corr.iloc[-1] == pytest.approx(1.0, abs=1e-12)

    def test_perfect_negative_log_return_correlation(self) -> None:
        index = pd.RangeIndex(50)
        pair_close = pd.Series(np.linspace(1.0, 1.10, 50), index=index)
        dxy = 1 / pair_close

        corr = dxy_correlation(pair_close, dxy, window=20)

        assert corr.iloc[-1] == pytest.approx(-1.0, abs=1e-12)

    def test_window_edge_rows_are_nan_until_full_return_window(self) -> None:
        index = pd.RangeIndex(10)
        pair_close = pd.Series(np.linspace(1.0, 1.09, 10), index=index)
        dxy = 2 * pair_close

        corr = dxy_correlation(pair_close, dxy, window=3)

        assert corr.iloc[:3].isna().all()
        assert np.isfinite(corr.iloc[3])

    def test_rejects_window_less_than_two(self) -> None:
        with pytest.raises(ValueError, match="window must be >= 2"):
            dxy_correlation(pd.Series([1.0, 1.1]), pd.Series([50.0, 51.0]), window=1)


class TestUsdPairCorrelations:
    def test_filters_to_usd_involving_pairs(self) -> None:
        index = pd.RangeIndex(30)
        pairs = {
            "EUR_USD": pd.DataFrame({"close": np.linspace(1.0, 1.05, 30)}, index=index),
            "USD_JPY": pd.DataFrame({"close": np.linspace(1.0, 1.03, 30)}, index=index),
            "EUR_GBP": pd.DataFrame({"close": np.linspace(1.0, 1.02, 30)}, index=index),
        }
        dxy = pd.Series(np.linspace(50.0, 52.0, 30), index=index)

        result = usd_pair_correlations(pairs, dxy, window=5)

        assert result.columns.tolist() == ["EUR_USD", "USD_JPY"]
        assert result.index.equals(dxy.index)

    def test_symbols_argument_restricts_output_columns(self) -> None:
        index = pd.RangeIndex(30)
        pairs = {
            "EUR_USD": pd.DataFrame({"close": np.linspace(1.0, 1.05, 30)}, index=index),
            "USD_JPY": pd.DataFrame({"close": np.linspace(1.0, 1.03, 30)}, index=index),
        }
        dxy = pd.Series(np.linspace(50.0, 52.0, 30), index=index)

        result = usd_pair_correlations(
            pairs,
            dxy,
            window=5,
            symbols=["EUR_USD"],
        )

        assert result.columns.tolist() == ["EUR_USD"]

    def test_returns_empty_frame_indexed_on_dxy_when_no_usd_pairs_remain(self) -> None:
        index = pd.RangeIndex(10)
        pairs = {"EUR_GBP": pd.DataFrame({"close": np.linspace(1.0, 1.02, 10)}, index=index)}
        dxy = pd.Series(np.linspace(50.0, 51.0, 10), index=index)

        result = usd_pair_correlations(pairs, dxy, window=3)

        assert result.empty
        assert result.index.equals(dxy.index)

