"""Validate daily OHLC aggregation and classic pivot calculations."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from bh_ftmo.indicators.pivots import _classic_pivots, daily_ohlc, pivots


PIVOT_COLUMNS = ["pp", "r1", "s1", "r2", "s2", "r3", "s3"]


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


def _expected_classic_pivots(high: float, low: float, close: float) -> dict[str, float]:
    pp = (high + low + close) / 3.0
    rng = high - low
    return {
        "pp": pp,
        "r1": 2 * pp - low,
        "s1": 2 * pp - high,
        "r2": pp + rng,
        "s2": pp - rng,
        "r3": high + 2 * (pp - low),
        "s3": low - 2 * (high - pp),
    }


class TestClassicPivots:
    def test_applies_classic_formula_to_daily_ohlc(self) -> None:
        daily = pd.DataFrame(
            {"open": [1.185], "high": [1.200], "low": [1.180], "close": [1.190]},
            index=[date(2024, 1, 5)],
        )
        expected = pd.DataFrame(
            [_expected_classic_pivots(1.200, 1.180, 1.190)],
            index=daily.index,
            columns=PIVOT_COLUMNS,
        )

        pd.testing.assert_frame_equal(_classic_pivots(daily), expected)


class TestDailyOhlc:
    def test_aggregates_by_new_york_calendar_day(self) -> None:
        timestamps = pd.Series(
            pd.to_datetime(
                [
                    "2024-01-02 23:00",
                    "2024-01-03 04:30",
                    "2024-01-03 05:00",
                    "2024-01-03 13:00",
                    "2024-01-04 04:59",
                    "2024-01-04 05:00",
                ]
            )
        )
        ohlc = _ohlc(
            open_=[1.100, 1.110, 1.120, 1.130, 1.140, 1.150],
            high=[1.120, 1.130, 1.150, 1.160, 1.170, 1.180],
            low=[1.090, 1.100, 1.110, 1.120, 1.125, 1.140],
            close=[1.110, 1.120, 1.130, 1.140, 1.150, 1.160],
        )
        expected = pd.DataFrame(
            {
                "open": [1.100, 1.120, 1.150],
                "high": [1.130, 1.170, 1.180],
                "low": [1.090, 1.110, 1.140],
                "close": [1.120, 1.150, 1.160],
            },
            index=[date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)],
        )

        pd.testing.assert_frame_equal(daily_ohlc(ohlc, timestamps=timestamps), expected)


class TestPivots:
    def test_first_trading_day_is_nan_and_monday_uses_friday_pivots(self) -> None:
        timestamps = pd.Series(
            pd.to_datetime(
                [
                    "2024-01-05 14:00",
                    "2024-01-05 18:00",
                    "2024-01-05 22:00",
                    "2024-01-08 14:00",
                    "2024-01-08 18:00",
                    "2024-01-08 22:00",
                ]
            )
        )
        ohlc = _ohlc(
            open_=[1.185, 1.186, 1.195, 1.205, 1.207, 1.204],
            high=[1.190, 1.200, 1.198, 1.210, 1.212, 1.209],
            low=[1.180, 1.183, 1.184, 1.200, 1.201, 1.199],
            close=[1.186, 1.195, 1.190, 1.207, 1.204, 1.206],
        )
        expected_friday = pd.Series(
            _expected_classic_pivots(1.200, 1.180, 1.190),
            name=3,
        )

        result = pivots(ohlc, timestamps=timestamps)

        assert result.loc[:2].isna().all(axis=None)
        for idx in [3, 4, 5]:
            pd.testing.assert_series_equal(
                result.loc[idx],
                expected_friday,
                check_names=False,
            )

    def test_timestamp_length_must_match_ohlc_length(self) -> None:
        ohlc = _ohlc([1.0, 1.1], [1.2, 1.2], [0.9, 1.0], [1.1, 1.15])
        timestamps = pd.Series(pd.to_datetime(["2024-01-05 14:00"]))

        try:
            pivots(ohlc, timestamps=timestamps)
        except ValueError as exc:
            assert "timestamps length 1 != ohlc length 2" in str(exc)
        else:
            raise AssertionError("pivots accepted mismatched timestamps")

    def test_uses_input_ohlc_index_for_result(self) -> None:
        timestamps = pd.Series(
            pd.to_datetime(
                [
                    "2024-01-05 14:00",
                    "2024-01-05 18:00",
                    "2024-01-08 14:00",
                ]
            )
        )
        ohlc = _ohlc(
            open_=[1.18, 1.19, 1.20],
            high=[1.20, 1.21, 1.22],
            low=[1.17, 1.18, 1.19],
            close=[1.19, 1.20, 1.21],
        )
        ohlc.index = pd.Index(["fri-1", "fri-2", "mon-1"], name="bar")

        result = pivots(ohlc, timestamps=timestamps)

        assert result.index.equals(ohlc.index)
        assert np.isnan(result.loc["fri-1", "pp"])
        assert np.isfinite(result.loc["mon-1", "pp"])
