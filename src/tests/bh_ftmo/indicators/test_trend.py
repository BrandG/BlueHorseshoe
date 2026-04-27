"""Validate bh_ftmo trend indicators against TA-Lib and hand references."""

from __future__ import annotations

import numpy as np
import pandas as pd
import talib

from bh_ftmo.indicators.trend import adx, donchian, ema, ichimoku, sma, supertrend
from tests.bh_ftmo.indicators.conftest import _last_n_compare


WILDER_RTOL = 1e-3
WILDER_ATOL = 1e-3
EXACT_RTOL = 1e-9
EXACT_ATOL = 1e-9


def _tiny_ohlc(close: list[float]) -> pd.DataFrame:
    close_arr = np.asarray(close, dtype=float)
    open_arr = np.empty_like(close_arr)
    open_arr[0] = close_arr[0]
    open_arr[1:] = close_arr[:-1]
    high = np.maximum(open_arr, close_arr) + 0.15
    low = np.minimum(open_arr, close_arr) - 0.15
    return pd.DataFrame(
        {"open": open_arr, "high": high, "low": low, "close": close_arr},
        index=pd.RangeIndex(len(close_arr)),
    )


class TestSma:
    def test_sma_20_matches_talib(self, ohlc_fixture: pd.DataFrame) -> None:
        period = 20
        bh = sma(ohlc_fixture, period=period)
        ta = talib.SMA(ohlc_fixture["close"].to_numpy(), timeperiod=period)

        _last_n_compare(bh, ta, period, rtol=EXACT_RTOL, atol=EXACT_ATOL)

    def test_sma_period_1_matches_talib(self, ohlc_fixture: pd.DataFrame) -> None:
        period = 1
        bh = sma(ohlc_fixture, period=period)

        # TA-Lib rejects SMA(timeperiod=1), so verify the edge-period identity.
        pd.testing.assert_series_equal(
            bh,
            ohlc_fixture["close"].rename("sma_1"),
            check_names=True,
        )


class TestEma:
    def test_ema_20_matches_talib_after_warmup(
        self,
        ohlc_fixture: pd.DataFrame,
    ) -> None:
        period = 20
        bh = ema(ohlc_fixture, period=period)
        ta = talib.EMA(ohlc_fixture["close"].to_numpy(), timeperiod=period)

        # bh_ftmo's pandas EWM seed differs from TA-Lib's first-window SMA seed.
        # The difference has decayed below 1e-3 by the RSI-established 12x buffer.
        _last_n_compare(
            bh,
            ta,
            n_warmup=period * 12,
            rtol=WILDER_RTOL,
            atol=WILDER_ATOL,
        )

    def test_ema_period_2_matches_talib_after_warmup(
        self,
        ohlc_fixture: pd.DataFrame,
    ) -> None:
        period = 2
        bh = ema(ohlc_fixture, period=period)
        ta = talib.EMA(ohlc_fixture["close"].to_numpy(), timeperiod=period)

        _last_n_compare(
            bh,
            ta,
            n_warmup=period * 12,
            rtol=WILDER_RTOL,
            atol=WILDER_ATOL,
        )


class TestAdx:
    def test_adx_14_matches_talib_after_warmup(
        self,
        ohlc_fixture: pd.DataFrame,
    ) -> None:
        period = 14
        bh = adx(ohlc_fixture, period=period)
        high = ohlc_fixture["high"].to_numpy()
        low = ohlc_fixture["low"].to_numpy()
        close = ohlc_fixture["close"].to_numpy()

        # ADX is double-smoothed, so keep the same 12x Wilder buffer used for RSI.
        warmup = period * 12
        _last_n_compare(
            bh["adx"],
            talib.ADX(high, low, close, timeperiod=period),
            warmup,
            rtol=WILDER_RTOL,
            atol=WILDER_ATOL,
        )
        _last_n_compare(
            bh["plus_di"],
            talib.PLUS_DI(high, low, close, timeperiod=period),
            warmup,
            rtol=WILDER_RTOL,
            atol=WILDER_ATOL,
        )
        _last_n_compare(
            bh["minus_di"],
            talib.MINUS_DI(high, low, close, timeperiod=period),
            warmup,
            rtol=WILDER_RTOL,
            atol=WILDER_ATOL,
        )

    def test_adx_period_5_matches_talib_after_warmup(
        self,
        ohlc_fixture: pd.DataFrame,
    ) -> None:
        period = 5
        bh = adx(ohlc_fixture, period=period)
        high = ohlc_fixture["high"].to_numpy()
        low = ohlc_fixture["low"].to_numpy()
        close = ohlc_fixture["close"].to_numpy()
        warmup = period * 12

        _last_n_compare(
            bh["adx"],
            talib.ADX(high, low, close, timeperiod=period),
            warmup,
            rtol=WILDER_RTOL,
            atol=WILDER_ATOL,
        )
        _last_n_compare(
            bh["plus_di"],
            talib.PLUS_DI(high, low, close, timeperiod=period),
            warmup,
            rtol=WILDER_RTOL,
            atol=WILDER_ATOL,
        )
        _last_n_compare(
            bh["minus_di"],
            talib.MINUS_DI(high, low, close, timeperiod=period),
            warmup,
            rtol=WILDER_RTOL,
            atol=WILDER_ATOL,
        )


class TestDonchian:
    def test_donchian_20_matches_hand_reference(self) -> None:
        ohlc = _tiny_ohlc(
            [
                10.0,
                10.3,
                10.1,
                10.7,
                10.5,
                10.9,
                11.2,
                10.8,
                10.4,
                10.6,
                11.0,
                11.4,
                11.1,
                10.9,
                10.2,
                9.8,
                10.0,
                10.5,
                10.9,
                11.3,
                11.6,
                11.2,
                10.7,
                10.1,
                9.6,
                9.9,
                10.4,
                10.8,
                11.1,
                11.5,
            ]
        )
        period = 20
        bh = donchian(ohlc, period=period)
        expected_upper = ohlc["high"].rolling(period, min_periods=period).max()
        expected_lower = ohlc["low"].rolling(period, min_periods=period).min()
        expected_middle = (expected_upper + expected_lower) / 2.0

        pd.testing.assert_series_equal(bh["upper"], expected_upper, check_names=False)
        pd.testing.assert_series_equal(bh["lower"], expected_lower, check_names=False)
        pd.testing.assert_series_equal(bh["middle"], expected_middle, check_names=False)

    def test_donchian_period_1_tracks_current_bar(self) -> None:
        ohlc = _tiny_ohlc([10.0, 10.4, 9.8, 10.2])
        bh = donchian(ohlc, period=1)

        pd.testing.assert_series_equal(bh["upper"], ohlc["high"], check_names=False)
        pd.testing.assert_series_equal(bh["lower"], ohlc["low"], check_names=False)
        pd.testing.assert_series_equal(
            bh["middle"],
            (ohlc["high"] + ohlc["low"]) / 2.0,
            check_names=False,
        )


class TestSupertrend:
    def test_supertrend_direction_flips_at_hand_computed_bars(self) -> None:
        ohlc = _tiny_ohlc(
            [
                10.0,
                9.8,
                9.6,
                9.4,
                9.2,
                9.0,
                9.4,
                9.8,
                10.4,
                11.0,
                11.5,
                11.9,
                11.4,
                10.8,
                10.1,
                9.4,
                8.9,
                8.5,
                8.8,
                9.3,
                9.9,
                10.6,
                11.2,
                10.7,
                10.0,
            ]
        )
        bh = supertrend(ohlc, period=3, multiplier=1.0)

        # Hand-walked final-band state machine using the implementation's
        # prior-bar-close carry-forward convention: seeded short at bar 2,
        # then flips long at 7, short at 13, long at 20, and short at 24.
        expected_direction = pd.Series(
            [
                0,
                0,
                -1,
                -1,
                -1,
                -1,
                -1,
                1,
                1,
                1,
                1,
                1,
                1,
                -1,
                -1,
                -1,
                -1,
                -1,
                -1,
                -1,
                1,
                1,
                1,
                1,
                -1,
            ],
            index=ohlc.index,
            dtype=np.int8,
            name="direction",
        )
        pd.testing.assert_series_equal(bh["direction"], expected_direction)

    def test_supertrend_period_1_returns_direction_for_every_bar_after_seed(
        self,
    ) -> None:
        ohlc = _tiny_ohlc([10.0, 10.6, 11.1, 10.4, 9.8, 10.5])
        bh = supertrend(ohlc, period=1, multiplier=1.0)

        assert bh["direction"].iloc[0] in (-1, 1)
        assert set(bh["direction"].iloc[1:].unique()) <= {-1, 1}


class TestIchimoku:
    def test_ichimoku_matches_hand_reference_with_shifts(self) -> None:
        ohlc = _tiny_ohlc(
            [
                10.0,
                10.4,
                10.2,
                10.8,
                11.0,
                10.7,
                10.5,
                10.9,
                11.3,
                11.1,
                10.6,
                10.2,
                9.9,
                10.1,
                10.5,
                10.8,
                11.2,
                11.6,
                11.4,
                11.0,
            ]
        )
        bh = ichimoku(
            ohlc,
            tenkan_period=3,
            kijun_period=5,
            senkou_b_period=7,
            displacement=3,
        )

        high = ohlc["high"]
        low = ohlc["low"]
        tenkan = (
            high.rolling(3, min_periods=3).max()
            + low.rolling(3, min_periods=3).min()
        ) / 2.0
        kijun = (
            high.rolling(5, min_periods=5).max()
            + low.rolling(5, min_periods=5).min()
        ) / 2.0
        senkou_b = (
            (
                high.rolling(7, min_periods=7).max()
                + low.rolling(7, min_periods=7).min()
            )
            / 2.0
        ).shift(3)

        pd.testing.assert_series_equal(bh["tenkan"], tenkan, check_names=False)
        pd.testing.assert_series_equal(bh["kijun"], kijun, check_names=False)
        pd.testing.assert_series_equal(
            bh["senkou_a"],
            ((tenkan + kijun) / 2.0).shift(3),
            check_names=False,
        )
        pd.testing.assert_series_equal(bh["senkou_b"], senkou_b, check_names=False)
        pd.testing.assert_series_equal(
            bh["chikou"],
            ohlc["close"].shift(-3),
            check_names=False,
        )

    def test_ichimoku_period_1_no_displacement_matches_current_midpoints(
        self,
    ) -> None:
        ohlc = _tiny_ohlc([10.0, 10.4, 9.9, 10.2])
        bh = ichimoku(
            ohlc,
            tenkan_period=1,
            kijun_period=1,
            senkou_b_period=1,
            displacement=0,
        )
        midpoint = (ohlc["high"] + ohlc["low"]) / 2.0

        pd.testing.assert_series_equal(bh["tenkan"], midpoint, check_names=False)
        pd.testing.assert_series_equal(bh["kijun"], midpoint, check_names=False)
        pd.testing.assert_series_equal(bh["senkou_a"], midpoint, check_names=False)
        pd.testing.assert_series_equal(bh["senkou_b"], midpoint, check_names=False)
        pd.testing.assert_series_equal(bh["chikou"], ohlc["close"], check_names=False)
