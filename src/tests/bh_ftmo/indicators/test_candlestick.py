"""Validate bh_ftmo candlestick anatomy helpers and pattern detectors."""

from __future__ import annotations

import pandas as pd
import pytest

from bh_ftmo.indicators.candlestick import (
    body_size,
    is_bearish,
    is_bearish_engulfing,
    is_bullish,
    is_bullish_engulfing,
    is_doji,
    is_hammer,
    is_shooting_star,
    lower_shadow,
    total_range,
    upper_shadow,
)


def _ohlc(
    open_: list[float],
    high: list[float],
    low: list[float],
    close: list[float],
) -> pd.DataFrame:
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close},
        index=pd.RangeIndex(len(close)),
    )


class TestAnatomy:
    def test_body_range_and_shadows_match_hand_arithmetic(self) -> None:
        ohlc = _ohlc(
            open_=[10.0, 12.0, 11.0, 9.5, 8.0],
            high=[11.0, 12.5, 11.2, 10.0, 8.0],
            low=[9.0, 10.0, 10.8, 9.0, 8.0],
            close=[10.5, 10.5, 11.0, 9.2, 8.0],
        )

        pd.testing.assert_series_equal(
            body_size(ohlc),
            pd.Series([0.5, 1.5, 0.0, 0.3, 0.0], name="body_size"),
            check_names=True,
        )
        pd.testing.assert_series_equal(
            total_range(ohlc),
            pd.Series([2.0, 2.5, 0.4, 1.0, 0.0], name="total_range"),
            check_names=True,
        )
        pd.testing.assert_series_equal(
            upper_shadow(ohlc),
            pd.Series([0.5, 0.5, 0.2, 0.5, 0.0], name="upper_shadow"),
            check_names=True,
        )
        pd.testing.assert_series_equal(
            lower_shadow(ohlc),
            pd.Series([1.0, 0.5, 0.2, 0.2, 0.0], name="lower_shadow"),
            check_names=True,
        )

    def test_direction_helpers_match_open_close_relationship(self) -> None:
        ohlc = _ohlc(
            open_=[10.0, 12.0, 11.0, 9.5, 8.0],
            high=[11.0, 12.5, 11.2, 10.0, 8.0],
            low=[9.0, 10.0, 10.8, 9.0, 8.0],
            close=[10.5, 10.5, 11.0, 9.2, 8.0],
        )

        pd.testing.assert_series_equal(
            is_bullish(ohlc),
            pd.Series([True, False, False, False, False], name="is_bullish"),
            check_names=True,
        )
        pd.testing.assert_series_equal(
            is_bearish(ohlc),
            pd.Series([False, True, False, True, False], name="is_bearish"),
            check_names=True,
        )


class TestDoji:
    def test_default_threshold_flags_only_small_body_nonflat_bars(self) -> None:
        ohlc = _ohlc(
            open_=[10.00, 10.00, 10.00, 10.00],
            high=[11.00, 11.00, 10.40, 10.00],
            low=[9.00, 9.00, 9.60, 10.00],
            close=[10.10, 10.30, 9.96, 10.00],
        )

        pd.testing.assert_series_equal(
            is_doji(ohlc),
            pd.Series([True, False, True, False], name="is_doji"),
            check_names=True,
        )

    def test_custom_threshold_can_be_stricter(self) -> None:
        ohlc = _ohlc(
            open_=[10.00, 10.00],
            high=[11.00, 11.00],
            low=[9.00, 9.00],
            close=[10.09, 10.06],
        )

        pd.testing.assert_series_equal(
            is_doji(ohlc, body_frac=0.05),
            pd.Series([True, True], name="is_doji"),
            check_names=True,
        )
        pd.testing.assert_series_equal(
            is_doji(ohlc, body_frac=0.04),
            pd.Series([False, True], name="is_doji"),
            check_names=True,
        )

    @pytest.mark.parametrize("body_frac", [0.0, 1.5])
    def test_rejects_out_of_range_body_fraction(self, body_frac: float) -> None:
        ohlc = _ohlc([10.0], [11.0], [9.0], [10.1])

        with pytest.raises(ValueError, match="body_frac must be in"):
            is_doji(ohlc, body_frac=body_frac)


class TestHammer:
    def test_default_shape_constraints_and_flat_bar(self) -> None:
        ohlc = _ohlc(
            open_=[10.0, 10.0, 10.0, 10.0],
            high=[10.5, 10.9, 10.8, 10.0],
            low=[8.5, 8.5, 9.3, 10.0],
            close=[10.3, 10.3, 10.4, 10.0],
        )

        pd.testing.assert_series_equal(
            is_hammer(ohlc),
            pd.Series([True, False, False, False], name="is_hammer"),
            check_names=True,
        )

    def test_custom_threshold_can_require_smaller_body(self) -> None:
        ohlc = _ohlc([10.0], [10.5], [8.5], [10.3])

        pd.testing.assert_series_equal(
            is_hammer(ohlc, body_frac_max=0.10),
            pd.Series([False], name="is_hammer"),
            check_names=True,
        )


class TestShootingStar:
    def test_default_shape_constraints_and_flat_bar(self) -> None:
        ohlc = _ohlc(
            open_=[10.0, 10.0, 10.0, 10.0],
            high=[11.5, 11.5, 10.7, 10.0],
            low=[9.8, 9.4, 9.7, 10.0],
            close=[10.3, 10.3, 10.3, 10.0],
        )

        pd.testing.assert_series_equal(
            is_shooting_star(ohlc),
            pd.Series([True, False, False, False], name="is_shooting_star"),
            check_names=True,
        )

    def test_custom_threshold_can_require_longer_upper_shadow(self) -> None:
        ohlc = _ohlc([10.0], [11.5], [9.8], [10.3])

        pd.testing.assert_series_equal(
            is_shooting_star(ohlc, upper_shadow_min=0.75),
            pd.Series([False], name="is_shooting_star"),
            check_names=True,
        )


class TestBullishEngulfing:
    def test_flags_two_bar_pattern_and_never_first_bar(self) -> None:
        ohlc = _ohlc(
            open_=[10.0, 9.2, 10.0, 10.1],
            high=[10.2, 11.2, 10.4, 10.4],
            low=[8.8, 9.0, 9.2, 9.0],
            close=[9.5, 10.8, 9.6, 10.2],
        )

        pd.testing.assert_series_equal(
            is_bullish_engulfing(ohlc),
            pd.Series(
                [False, True, False, False],
                name="is_bullish_engulfing",
            ),
            check_names=True,
        )

    def test_custom_min_body_fraction_filters_small_prior_body(self) -> None:
        ohlc = _ohlc([10.0, 9.8], [10.5, 10.7], [9.4, 9.6], [9.7, 10.2])

        pd.testing.assert_series_equal(
            is_bullish_engulfing(ohlc, min_body_frac=0.50),
            pd.Series([False, False], name="is_bullish_engulfing"),
            check_names=True,
        )

    @pytest.mark.parametrize("min_body_frac", [0.0, 1.5])
    def test_rejects_out_of_range_min_body_fraction(
        self,
        min_body_frac: float,
    ) -> None:
        ohlc = _ohlc([10.0, 9.2], [10.2, 11.2], [8.8, 9.0], [9.5, 10.8])

        with pytest.raises(ValueError, match="min_body_frac must be in"):
            is_bullish_engulfing(ohlc, min_body_frac=min_body_frac)


class TestBearishEngulfing:
    def test_flags_two_bar_pattern_and_never_first_bar(self) -> None:
        ohlc = _ohlc(
            open_=[10.0, 10.8, 10.0, 9.9],
            high=[11.2, 11.0, 10.8, 10.1],
            low=[9.8, 8.8, 9.6, 9.6],
            close=[10.5, 9.2, 10.4, 9.8],
        )

        pd.testing.assert_series_equal(
            is_bearish_engulfing(ohlc),
            pd.Series(
                [False, True, False, False],
                name="is_bearish_engulfing",
            ),
            check_names=True,
        )

    def test_custom_min_body_fraction_filters_small_prior_body(self) -> None:
        ohlc = _ohlc([10.0, 10.2], [10.6, 10.4], [9.8, 9.4], [10.3, 9.8])

        pd.testing.assert_series_equal(
            is_bearish_engulfing(ohlc, min_body_frac=0.50),
            pd.Series([False, False], name="is_bearish_engulfing"),
            check_names=True,
        )

    @pytest.mark.parametrize("min_body_frac", [0.0, 1.5])
    def test_rejects_out_of_range_min_body_fraction(
        self,
        min_body_frac: float,
    ) -> None:
        ohlc = _ohlc([10.0, 10.8], [11.2, 11.0], [9.8, 8.8], [10.5, 9.2])

        with pytest.raises(ValueError, match="min_body_frac must be in"):
            is_bearish_engulfing(ohlc, min_body_frac=min_body_frac)
