"""Validate shared OHLC helpers."""

from __future__ import annotations

import pandas as pd
import pytest

from bh_ftmo.indicators._common import _require_ohlc, ohlc_mid


class TestOhlcMid:
    def test_averages_bid_ask_ohlc_and_preserves_index(self) -> None:
        index = pd.Index(["bar-1", "bar-2"], name="bar")
        df = pd.DataFrame(
            {
                "open_bid": [1.1000, 1.1100],
                "open_ask": [1.1002, 1.1104],
                "high_bid": [1.1200, 1.1300],
                "high_ask": [1.1204, 1.1302],
                "low_bid": [1.0900, 1.1000],
                "low_ask": [1.0902, 1.1006],
                "close_bid": [1.1050, 1.1150],
                "close_ask": [1.1054, 1.1152],
            },
            index=index,
        )
        expected = pd.DataFrame(
            {
                "open": [1.1001, 1.1102],
                "high": [1.1202, 1.1301],
                "low": [1.0901, 1.1003],
                "close": [1.1052, 1.1151],
            },
            index=index,
        )

        pd.testing.assert_frame_equal(ohlc_mid(df), expected)


class TestRequireOhlc:
    def test_accepts_valid_ohlc_frame(self) -> None:
        ohlc = pd.DataFrame(
            {"open": [1.0], "high": [1.2], "low": [0.9], "close": [1.1]}
        )

        assert _require_ohlc(ohlc) is None

    def test_raises_with_missing_column_names(self) -> None:
        ohlc = pd.DataFrame({"open": [1.0], "low": [0.9]})

        with pytest.raises(ValueError) as excinfo:
            _require_ohlc(ohlc)

        message = str(excinfo.value)
        assert "high" in message
        assert "close" in message

