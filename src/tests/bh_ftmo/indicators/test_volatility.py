"""Validate bh_ftmo volatility indicators against TA-Lib and hand references."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import talib

from bh_ftmo.indicators.volatility import (
    atr,
    atr_percent,
    bollinger_bands,
    true_range,
)
from tests.bh_ftmo.indicators.conftest import _last_n_compare


WILDER_RTOL = 1e-3
WILDER_ATOL = 1e-3
EXACT_RTOL = 1e-9
EXACT_ATOL = 1e-9


def _tiny_ohlc(
    high: list[float],
    low: list[float],
    close: list[float],
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": close,
            "high": high,
            "low": low,
            "close": close,
        },
        index=pd.RangeIndex(len(close)),
    )


class TestTrueRange:
    def test_true_range_matches_hand_computed_components(self) -> None:
        ohlc = _tiny_ohlc(
            high=[10.0, 10.7, 10.2, 11.4, 10.6],
            low=[9.5, 9.8, 9.4, 10.1, 9.9],
            close=[9.8, 10.1, 9.6, 10.9, 10.0],
        )
        prev_close = ohlc["close"].shift(1)
        expected = pd.concat(
            [
                ohlc["high"] - ohlc["low"],
                (ohlc["high"] - prev_close).abs(),
                (ohlc["low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        expected.name = "true_range"

        pd.testing.assert_series_equal(true_range(ohlc), expected)

    def test_true_range_matches_talib_from_second_bar(
        self,
        ohlc_fixture: pd.DataFrame,
    ) -> None:
        high = ohlc_fixture["high"].to_numpy()
        low = ohlc_fixture["low"].to_numpy()
        close = ohlc_fixture["close"].to_numpy()

        # bh_ftmo defines TR[0] as H-L; TA-Lib returns NaN because there is no
        # previous close. From bar 1 onward the conventions agree.
        _last_n_compare(
            true_range(ohlc_fixture),
            talib.TRANGE(high, low, close),
            n_warmup=1,
            rtol=EXACT_RTOL,
            atol=EXACT_ATOL,
        )


class TestAtr:
    def test_atr_14_matches_talib_after_warmup(
        self,
        ohlc_fixture: pd.DataFrame,
    ) -> None:
        period = 14
        high = ohlc_fixture["high"].to_numpy()
        low = ohlc_fixture["low"].to_numpy()
        close = ohlc_fixture["close"].to_numpy()

        # pandas EWM and TA-Lib seed Wilder smoothing differently; the seed
        # mismatch has decayed below 1e-3 by the RSI-established 12x buffer.
        _last_n_compare(
            atr(ohlc_fixture, period=period),
            talib.ATR(high, low, close, timeperiod=period),
            n_warmup=period * 12,
            rtol=WILDER_RTOL,
            atol=WILDER_ATOL,
        )

    def test_atr_period_1_matches_true_range_after_first_bar(
        self,
        ohlc_fixture: pd.DataFrame,
    ) -> None:
        bh = atr(ohlc_fixture, period=1)
        expected = true_range(ohlc_fixture)

        pd.testing.assert_series_equal(
            bh.iloc[1:],
            expected.iloc[1:],
            check_names=False,
        )


class TestAtrPercent:
    def test_atr_percent_matches_atr_divided_by_close(
        self,
        ohlc_fixture: pd.DataFrame,
    ) -> None:
        period = 14
        expected = atr(ohlc_fixture, period=period) / ohlc_fixture["close"]
        expected.name = "atr_percent"

        pd.testing.assert_series_equal(
            atr_percent(ohlc_fixture, period=period),
            expected,
        )

    def test_atr_percent_replaces_zero_close_with_nan(self) -> None:
        ohlc = _tiny_ohlc(
            high=[10.0, 10.7, 11.2],
            low=[9.5, 9.8, 10.4],
            close=[9.8, 0.0, 10.6],
        )
        bh = atr_percent(ohlc, period=1)

        assert np.isnan(bh.iloc[1])
        assert np.isfinite(bh.iloc[2])


class TestBollingerBands:
    def test_bollinger_bands_20_matches_talib_population_stddev(
        self,
        ohlc_fixture: pd.DataFrame,
    ) -> None:
        period = 20
        close = ohlc_fixture["close"].to_numpy()
        bh = bollinger_bands(ohlc_fixture, period=period, n_std=2.0)
        ta_upper, ta_middle, ta_lower = talib.BBANDS(
            close,
            timeperiod=period,
            nbdevup=2,
            nbdevdn=2,
            matype=0,
        )

        first = period - 1
        ta_std = (ta_upper[first] - ta_middle[first]) / 2.0
        assert ta_std == pytest.approx(
            np.std(close[:period], ddof=0),
            rel=EXACT_RTOL,
            abs=EXACT_ATOL,
        )
        assert ta_std != pytest.approx(
            np.std(close[:period], ddof=1),
            rel=EXACT_RTOL,
            abs=EXACT_ATOL,
        )

        _last_n_compare(
            bh["upper"],
            ta_upper,
            n_warmup=first,
            rtol=EXACT_RTOL,
            atol=EXACT_ATOL,
        )
        _last_n_compare(
            bh["middle"],
            ta_middle,
            n_warmup=first,
            rtol=EXACT_RTOL,
            atol=EXACT_ATOL,
        )
        _last_n_compare(
            bh["lower"],
            ta_lower,
            n_warmup=first,
            rtol=EXACT_RTOL,
            atol=EXACT_ATOL,
        )

        expected_pct_b = (ohlc_fixture["close"] - bh["lower"]) / (
            bh["upper"] - bh["lower"]
        )
        expected_bandwidth = (bh["upper"] - bh["lower"]) / bh["middle"]

        pd.testing.assert_series_equal(
            bh["pct_b"],
            expected_pct_b,
            check_names=False,
        )
        pd.testing.assert_series_equal(
            bh["bandwidth"],
            expected_bandwidth,
            check_names=False,
        )

    def test_bollinger_bands_period_2_matches_hand_reference(self) -> None:
        ohlc = _tiny_ohlc(
            high=[10.1, 10.5, 11.2, 10.8],
            low=[9.8, 10.0, 10.4, 10.1],
            close=[10.0, 10.4, 10.8, 10.2],
        )
        bh = bollinger_bands(ohlc, period=2, n_std=1.5)
        middle = ohlc["close"].rolling(2, min_periods=2).mean()
        std = ohlc["close"].rolling(2, min_periods=2).std(ddof=0)
        upper = middle + 1.5 * std
        lower = middle - 1.5 * std

        pd.testing.assert_series_equal(bh["middle"], middle, check_names=False)
        pd.testing.assert_series_equal(bh["upper"], upper, check_names=False)
        pd.testing.assert_series_equal(bh["lower"], lower, check_names=False)

    def test_bollinger_bands_flat_window_has_nan_pct_b(self) -> None:
        ohlc = _tiny_ohlc(
            high=[10.1, 10.1, 10.1],
            low=[9.9, 9.9, 9.9],
            close=[10.0, 10.0, 10.0],
        )
        bh = bollinger_bands(ohlc, period=2, n_std=2.0)

        assert bh["pct_b"].iloc[1:].isna().all()
        assert (bh["bandwidth"].iloc[1:] == 0.0).all()
