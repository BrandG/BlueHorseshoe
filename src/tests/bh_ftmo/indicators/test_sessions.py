"""Validate forex session classification and per-session ranges."""

from __future__ import annotations

from datetime import date

import pandas as pd

from bh_ftmo.data.fx_time_utils import NY
from bh_ftmo.indicators.sessions import (
    SESSION_HOURS,
    Session,
    _classify_hour,
    _hour_in_window,
    session_label,
    session_ranges,
)


class TestHourInWindow:
    def test_non_wrapping_window_is_half_open(self) -> None:
        assert _hour_in_window(8, 8, 12)
        assert _hour_in_window(11, 8, 12)
        assert not _hour_in_window(12, 8, 12)
        assert not _hour_in_window(7, 8, 12)

    def test_wrapping_window_covers_both_legs(self) -> None:
        assert _hour_in_window(17, 17, 3)
        assert _hour_in_window(23, 17, 3)
        assert _hour_in_window(2, 17, 3)
        assert not _hour_in_window(3, 17, 3)
        assert not _hour_in_window(15, 17, 3)


class TestClassifyHour:
    def test_default_session_hours_cover_every_wall_clock_hour(self) -> None:
        labels = [_classify_hour(hour, SESSION_HOURS) for hour in range(24)]

        assert set(labels) == {Session.ASIA, Session.LONDON, Session.OVERLAP, Session.NY}
        assert labels.count(Session.ASIA) == 10
        assert labels.count(Session.LONDON) == 5
        assert labels.count(Session.OVERLAP) == 4
        assert labels.count(Session.NY) == 5

    def test_boundaries_classify_to_expected_sessions(self) -> None:
        assert _classify_hour(2, SESSION_HOURS) is Session.ASIA
        assert _classify_hour(3, SESSION_HOURS) is Session.LONDON
        assert _classify_hour(8, SESSION_HOURS) is Session.OVERLAP
        assert _classify_hour(12, SESSION_HOURS) is Session.NY
        assert _classify_hour(17, SESSION_HOURS) is Session.ASIA


class TestSessionLabel:
    def test_dst_is_handled_by_utc_to_new_york_conversion(self) -> None:
        timestamps = pd.Series(
            pd.to_datetime(
                [
                    "2024-07-15 13:00",
                    "2024-12-16 13:00",
                    "2024-07-15 12:00",
                    "2024-12-16 12:00",
                ],
                utc=True,
            )
        )

        result = session_label(timestamps)

        assert timestamps.iloc[0].tz_convert(NY).strftime("%Y-%m-%d %H:%M %Z") == (
            "2024-07-15 09:00 EDT"
        )
        assert timestamps.iloc[1].tz_convert(NY).strftime("%Y-%m-%d %H:%M %Z") == (
            "2024-12-16 08:00 EST"
        )
        assert timestamps.iloc[2].tz_convert(NY).strftime("%Y-%m-%d %H:%M %Z") == (
            "2024-07-15 08:00 EDT"
        )
        assert timestamps.iloc[3].tz_convert(NY).strftime("%Y-%m-%d %H:%M %Z") == (
            "2024-12-16 07:00 EST"
        )
        assert result.tolist() == [
            Session.OVERLAP,
            Session.OVERLAP,
            Session.OVERLAP,
            Session.LONDON,
        ]

    def test_weekend_bar_is_closed_regardless_of_new_york_hour(self) -> None:
        timestamps = pd.Series(pd.to_datetime(["2024-07-13 16:00"], utc=True))

        result = session_label(timestamps)

        assert timestamps.iloc[0].tz_convert(NY).strftime("%Y-%m-%d %H:%M %Z") == (
            "2024-07-13 12:00 EDT"
        )
        assert result.iloc[0] is Session.CLOSED

    def test_preserves_input_index_and_series_name(self) -> None:
        timestamps = pd.Series(
            pd.to_datetime(["2024-01-08 13:00", "2024-01-08 17:00"], utc=True),
            index=pd.Index(["overlap", "ny"], name="bar"),
        )

        result = session_label(timestamps)

        assert result.name == "session"
        assert result.index.equals(timestamps.index)
        assert result.tolist() == [Session.OVERLAP, Session.NY]


class TestSessionRanges:
    def test_aggregates_by_new_york_date_and_session_excluding_closed_bars(self) -> None:
        timestamps = pd.Series(
            pd.to_datetime(
                [
                    "2024-01-06 17:00",  # Saturday CLOSED, otherwise NY session hour.
                    "2024-01-08 13:00",
                    "2024-01-08 14:00",
                    "2024-01-08 17:00",
                    "2024-01-08 18:00",
                    "2024-01-09 13:00",
                    "2024-01-09 14:00",
                    "2024-01-09 17:00",
                    "2024-01-09 18:00",
                ],
                utc=True,
            )
        )
        ohlc = pd.DataFrame(
            {
                "open": [9.0, 1.10, 1.11, 1.20, 1.21, 1.30, 1.31, 1.40, 1.41],
                "high": [9.5, 1.15, 1.18, 1.24, 1.26, 1.35, 1.38, 1.44, 1.46],
                "low": [8.5, 1.08, 1.09, 1.18, 1.19, 1.28, 1.29, 1.38, 1.39],
                "close": [9.2, 1.12, 1.17, 1.22, 1.25, 1.32, 1.37, 1.42, 1.45],
            }
        )
        expected_index = pd.MultiIndex.from_tuples(
            [
                (date(2024, 1, 8), "ny"),
                (date(2024, 1, 8), "overlap"),
                (date(2024, 1, 9), "ny"),
                (date(2024, 1, 9), "overlap"),
            ],
            names=["date", "session"],
        )
        expected = pd.DataFrame(
            {
                "open": [1.20, 1.10, 1.40, 1.30],
                "high": [1.26, 1.18, 1.46, 1.38],
                "low": [1.18, 1.08, 1.38, 1.28],
                "close": [1.25, 1.17, 1.45, 1.37],
            },
            index=expected_index,
        )

        result = session_ranges(ohlc, timestamps=timestamps)

        pd.testing.assert_frame_equal(result, expected)

    def test_timestamp_length_must_match_ohlc_length(self) -> None:
        ohlc = pd.DataFrame(
            {"open": [1.0], "high": [1.1], "low": [0.9], "close": [1.05]}
        )
        timestamps = pd.Series(pd.to_datetime(["2024-01-08 13:00", "2024-01-08 14:00"]))

        try:
            session_ranges(ohlc, timestamps=timestamps)
        except ValueError as exc:
            assert "timestamps length 2 != ohlc length 1" in str(exc)
        else:
            raise AssertionError("session_ranges accepted mismatched timestamps")

