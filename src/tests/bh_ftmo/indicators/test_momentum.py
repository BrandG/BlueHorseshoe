"""Validate bh_ftmo momentum indicators against TA-Lib references.

RSI and MACD use pandas EMA seeding in bh_ftmo, while TA-Lib seeds from the
first completed window. Those warmup differences are expected to decay. The
tests below compare the converged region and keep edge-period coverage for
off-by-one mistakes.
"""

from __future__ import annotations

import pandas as pd
import talib

from bh_ftmo.indicators.momentum import cci, macd, rsi, stochastic, williams_r
from tests.bh_ftmo.indicators.conftest import _last_n_compare


WILDER_RTOL = 1e-3
WILDER_ATOL = 1e-3
EXACT_RTOL = 1e-9
EXACT_ATOL = 1e-9


class TestRsi:
    def test_rsi_14_matches_talib_after_warmup(self, ohlc_fixture: pd.DataFrame) -> None:
        period = 14
        bh = rsi(ohlc_fixture, period=period)
        ta = talib.RSI(ohlc_fixture["close"].to_numpy(), timeperiod=period)

        # TA-Lib's SMA seed leaves RSI(14) about 0.33 points apart at 5x
        # period on this fixture; by 12x period it is below the 1e-3 bound.
        _last_n_compare(
            bh,
            ta,
            n_warmup=period * 12,
            rtol=WILDER_RTOL,
            atol=WILDER_ATOL,
        )

    def test_rsi_period_2_matches_talib_after_warmup(
        self,
        ohlc_fixture: pd.DataFrame,
    ) -> None:
        period = 2
        bh = rsi(ohlc_fixture, period=period)
        ta = talib.RSI(ohlc_fixture["close"].to_numpy(), timeperiod=period)

        _last_n_compare(
            bh,
            ta,
            n_warmup=period * 5,
            rtol=WILDER_RTOL,
            atol=WILDER_ATOL,
        )


class TestMacd:
    def test_macd_default_matches_talib_after_warmup(
        self,
        ohlc_fixture: pd.DataFrame,
    ) -> None:
        bh = macd(ohlc_fixture, fast=12, slow=26, signal=9)
        ta_macd, ta_signal, ta_hist = talib.MACD(
            ohlc_fixture["close"].to_numpy(),
            fastperiod=12,
            slowperiod=26,
            signalperiod=9,
        )
        warmup = (26 + 9) * 3

        _last_n_compare(bh["macd"], ta_macd, warmup, rtol=WILDER_RTOL, atol=WILDER_ATOL)
        _last_n_compare(
            bh["signal"],
            ta_signal,
            warmup,
            rtol=WILDER_RTOL,
            atol=WILDER_ATOL,
        )
        _last_n_compare(
            bh["histogram"],
            ta_hist,
            warmup,
            rtol=WILDER_RTOL,
            atol=WILDER_ATOL,
        )

    def test_macd_short_periods_match_talib_after_warmup(
        self,
        ohlc_fixture: pd.DataFrame,
    ) -> None:
        bh = macd(ohlc_fixture, fast=3, slow=10, signal=4)
        ta_macd, ta_signal, ta_hist = talib.MACD(
            ohlc_fixture["close"].to_numpy(),
            fastperiod=3,
            slowperiod=10,
            signalperiod=4,
        )
        warmup = (10 + 4) * 3

        _last_n_compare(bh["macd"], ta_macd, warmup, rtol=WILDER_RTOL, atol=WILDER_ATOL)
        _last_n_compare(
            bh["signal"],
            ta_signal,
            warmup,
            rtol=WILDER_RTOL,
            atol=WILDER_ATOL,
        )
        _last_n_compare(
            bh["histogram"],
            ta_hist,
            warmup,
            rtol=WILDER_RTOL,
            atol=WILDER_ATOL,
        )


class TestStochastic:
    def test_stochastic_matches_talib_stochf(self, ohlc_fixture: pd.DataFrame) -> None:
        # bh_ftmo implements fast stochastic, so STOCHF is the correct reference.
        bh = stochastic(ohlc_fixture, k_period=14, d_period=3)
        ta_k, ta_d = talib.STOCHF(
            ohlc_fixture["high"].to_numpy(),
            ohlc_fixture["low"].to_numpy(),
            ohlc_fixture["close"].to_numpy(),
            fastk_period=14,
            fastd_period=3,
            fastd_matype=0,
        )
        warmup = 14 + 3

        _last_n_compare(bh["k"], ta_k, warmup, rtol=EXACT_RTOL, atol=EXACT_ATOL)
        _last_n_compare(bh["d"], ta_d, warmup, rtol=EXACT_RTOL, atol=EXACT_ATOL)

    def test_stochastic_short_periods_match_talib_stochf(
        self,
        ohlc_fixture: pd.DataFrame,
    ) -> None:
        bh = stochastic(ohlc_fixture, k_period=2, d_period=2)
        ta_k, ta_d = talib.STOCHF(
            ohlc_fixture["high"].to_numpy(),
            ohlc_fixture["low"].to_numpy(),
            ohlc_fixture["close"].to_numpy(),
            fastk_period=2,
            fastd_period=2,
            fastd_matype=0,
        )
        warmup = 2 + 2

        _last_n_compare(bh["k"], ta_k, warmup, rtol=EXACT_RTOL, atol=EXACT_ATOL)
        _last_n_compare(bh["d"], ta_d, warmup, rtol=EXACT_RTOL, atol=EXACT_ATOL)


class TestCci:
    def test_cci_20_matches_talib(self, ohlc_fixture: pd.DataFrame) -> None:
        period = 20
        bh = cci(ohlc_fixture, period=period)
        ta = talib.CCI(
            ohlc_fixture["high"].to_numpy(),
            ohlc_fixture["low"].to_numpy(),
            ohlc_fixture["close"].to_numpy(),
            timeperiod=period,
        )

        _last_n_compare(bh, ta, n_warmup=period, rtol=EXACT_RTOL, atol=EXACT_ATOL)

    def test_cci_period_2_matches_talib(self, ohlc_fixture: pd.DataFrame) -> None:
        period = 2
        bh = cci(ohlc_fixture, period=period)
        ta = talib.CCI(
            ohlc_fixture["high"].to_numpy(),
            ohlc_fixture["low"].to_numpy(),
            ohlc_fixture["close"].to_numpy(),
            timeperiod=period,
        )

        _last_n_compare(bh, ta, n_warmup=period, rtol=EXACT_RTOL, atol=EXACT_ATOL)


class TestWilliamsR:
    def test_williams_r_14_matches_talib(self, ohlc_fixture: pd.DataFrame) -> None:
        period = 14
        bh = williams_r(ohlc_fixture, period=period)
        ta = talib.WILLR(
            ohlc_fixture["high"].to_numpy(),
            ohlc_fixture["low"].to_numpy(),
            ohlc_fixture["close"].to_numpy(),
            timeperiod=period,
        )

        _last_n_compare(bh, ta, n_warmup=period, rtol=EXACT_RTOL, atol=EXACT_ATOL)

    def test_williams_r_period_2_matches_talib(
        self,
        ohlc_fixture: pd.DataFrame,
    ) -> None:
        period = 2
        bh = williams_r(ohlc_fixture, period=period)
        ta = talib.WILLR(
            ohlc_fixture["high"].to_numpy(),
            ohlc_fixture["low"].to_numpy(),
            ohlc_fixture["close"].to_numpy(),
            timeperiod=period,
        )

        _last_n_compare(bh, ta, n_warmup=period, rtol=EXACT_RTOL, atol=EXACT_ATOL)
