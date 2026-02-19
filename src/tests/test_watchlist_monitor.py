"""Tests for watchlist monitor functionality."""
import csv
import os
import tempfile
from datetime import datetime
from io import StringIO
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from bluehorseshoe.data.ibkr_client import QuoteData
from bluehorseshoe.data.watchlist_monitor import (
    WatchlistMonitor,
    _nyse_holidays_for_year,
    load_watchlist,
)


# ---------------------------------------------------------------------------
# load_watchlist tests
# ---------------------------------------------------------------------------


def test_load_watchlist(tmp_path):
    """Reads file, skips comments and blanks, uppercases symbols."""
    wl = tmp_path / "watchlist.txt"
    wl.write_text("# Header comment\naapl\n\n  MSFT  \n# another comment\ngoog\n")
    result = load_watchlist(str(wl))
    assert result == ["AAPL", "MSFT", "GOOG"]


def test_load_watchlist_missing_file():
    """Returns empty list when file does not exist — no crash."""
    result = load_watchlist("/nonexistent/path/watchlist.txt")
    assert result == []


# ---------------------------------------------------------------------------
# _display tests
# ---------------------------------------------------------------------------


def test_display_format(capsys):
    """Verify table structure in terminal output."""
    client = MagicMock()
    monitor = WatchlistMonitor(client=client, symbols=["AAPL", "MSFT"])

    quotes = [
        QuoteData(
            symbol="AAPL", last=245.12, bid=245.10, ask=245.15,
            open=244.00, high=246.50, low=243.80, close=244.00,
            volume=12345678, timestamp=datetime(2026, 2, 19, 10, 30, 1),
        ),
        QuoteData(
            symbol="MSFT", last=410.50, bid=410.45, ask=410.55,
            open=409.00, high=411.00, low=408.50, close=409.00,
            volume=8765432, timestamp=datetime(2026, 2, 19, 10, 30, 1),
        ),
    ]

    monitor._display(quotes)
    output = capsys.readouterr().out

    # Table header
    assert "Symbol" in output
    assert "Last" in output
    assert "Bid" in output
    assert "Volume" in output

    # Data rows
    assert "AAPL" in output
    assert "245.12" in output
    assert "MSFT" in output
    assert "410.50" in output

    # Separators
    assert "=" * 90 in output


def test_display_with_error_quotes(capsys):
    """Quotes with .error display gracefully inline."""
    client = MagicMock()
    monitor = WatchlistMonitor(client=client, symbols=["BAD"])

    quotes = [
        QuoteData(symbol="BAD", error="Connection refused"),
    ]

    monitor._display(quotes)
    output = capsys.readouterr().out

    assert "BAD" in output
    assert "ERROR" in output
    assert "Connection refused" in output


# ---------------------------------------------------------------------------
# _log_csv tests
# ---------------------------------------------------------------------------


def test_csv_logging(tmp_path):
    """Write to temp file, verify header + data rows."""
    csv_file = str(tmp_path / "watchlist_test.csv")
    client = MagicMock()
    monitor = WatchlistMonitor(client=client, symbols=["AAPL"], csv_path=csv_file)

    quotes = [
        QuoteData(
            symbol="AAPL", last=245.12, bid=245.10, ask=245.15,
            open=244.00, high=246.50, low=243.80, close=244.00,
            volume=12345678, timestamp=datetime(2026, 2, 19, 10, 30, 1),
        ),
    ]

    # First write — should create header
    monitor._log_csv(quotes)

    with open(csv_file, "r", encoding="utf-8") as f:
        reader = list(csv.reader(f))

    assert len(reader) == 2  # header + 1 data row
    assert reader[0] == ["timestamp", "symbol", "last", "bid", "ask", "open", "high", "low", "volume"]
    assert reader[1][1] == "AAPL"
    assert reader[1][2] == "245.12"

    # Second write — no duplicate header
    monitor._log_csv(quotes)

    with open(csv_file, "r", encoding="utf-8") as f:
        reader = list(csv.reader(f))

    assert len(reader) == 3  # header + 2 data rows


def test_csv_skips_error_quotes(tmp_path):
    """Error quotes should not be written to CSV."""
    csv_file = str(tmp_path / "watchlist_test.csv")
    client = MagicMock()
    monitor = WatchlistMonitor(client=client, symbols=["BAD"], csv_path=csv_file)

    quotes = [QuoteData(symbol="BAD", error="Connection refused")]
    monitor._log_csv(quotes)

    with open(csv_file, "r", encoding="utf-8") as f:
        reader = list(csv.reader(f))

    # Only header, no data rows
    assert len(reader) == 1


# ---------------------------------------------------------------------------
# _poll tests
# ---------------------------------------------------------------------------


def test_poll_delegates_to_client():
    """_poll calls client.get_quotes with the symbol list."""
    client = MagicMock()
    expected = [QuoteData(symbol="AAPL", last=245.0)]
    client.get_quotes.return_value = expected

    monitor = WatchlistMonitor(client=client, symbols=["AAPL"])
    result = monitor._poll()

    client.get_quotes.assert_called_once_with(["AAPL"])
    assert result == expected


def test_poll_with_mixed_errors():
    """Quotes with errors are returned alongside valid ones."""
    client = MagicMock()
    client.get_quotes.return_value = [
        QuoteData(symbol="AAPL", last=245.0, timestamp=datetime.now()),
        QuoteData(symbol="BAD", error="No data"),
    ]

    monitor = WatchlistMonitor(client=client, symbols=["AAPL", "BAD"])
    result = monitor._poll()

    assert len(result) == 2
    assert result[0].last == 245.0
    assert result[1].error == "No data"


# ---------------------------------------------------------------------------
# _is_market_open tests
# ---------------------------------------------------------------------------

ET = ZoneInfo("America/New_York")


def test_market_open_midday_weekday():
    """Tuesday at noon ET should be open."""
    # 2026-02-17 is a Tuesday
    t = datetime(2026, 2, 17, 12, 0, 0, tzinfo=ET)
    assert WatchlistMonitor._is_market_open(t) is True


def test_market_closed_before_open():
    """Weekday at 9:00 ET (before 9:30) should be closed."""
    t = datetime(2026, 2, 17, 9, 0, 0, tzinfo=ET)
    assert WatchlistMonitor._is_market_open(t) is False


def test_market_open_at_930():
    """Weekday at exactly 9:30 ET should be open."""
    t = datetime(2026, 2, 17, 9, 30, 0, tzinfo=ET)
    assert WatchlistMonitor._is_market_open(t) is True


def test_market_closed_at_1600():
    """Weekday at exactly 16:00 ET should be closed (close is exclusive)."""
    t = datetime(2026, 2, 17, 16, 0, 0, tzinfo=ET)
    assert WatchlistMonitor._is_market_open(t) is False


def test_market_closed_after_hours():
    """Weekday at 18:00 ET should be closed."""
    t = datetime(2026, 2, 17, 18, 0, 0, tzinfo=ET)
    assert WatchlistMonitor._is_market_open(t) is False


def test_market_closed_saturday():
    """Saturday should be closed regardless of time."""
    # 2026-02-21 is a Saturday
    t = datetime(2026, 2, 21, 12, 0, 0, tzinfo=ET)
    assert WatchlistMonitor._is_market_open(t) is False


def test_market_closed_sunday():
    """Sunday should be closed regardless of time."""
    # 2026-02-22 is a Sunday
    t = datetime(2026, 2, 22, 12, 0, 0, tzinfo=ET)
    assert WatchlistMonitor._is_market_open(t) is False


def test_display_closed_banner(capsys):
    """Market-closed banner shows the right message."""
    client = MagicMock()
    monitor = WatchlistMonitor(client=client, symbols=["AAPL", "MSFT"])
    monitor._display_closed()
    output = capsys.readouterr().out
    assert "Market is closed" in output
    assert "9:30-16:00 ET" in output
    assert "excluding holidays" in output


# ---------------------------------------------------------------------------
# NYSE holiday tests
# ---------------------------------------------------------------------------

import datetime as _dt


def test_market_closed_new_years_day():
    """New Year's Day 2026 (Thu Jan 1) — NYSE closed."""
    t = datetime(2026, 1, 1, 12, 0, 0, tzinfo=ET)
    assert WatchlistMonitor._is_market_open(t) is False


def test_market_closed_mlk_day():
    """MLK Day 2026 (Mon Jan 19) — NYSE closed."""
    t = datetime(2026, 1, 19, 12, 0, 0, tzinfo=ET)
    assert WatchlistMonitor._is_market_open(t) is False


def test_market_closed_good_friday():
    """Good Friday 2026 (Fri Apr 3) — NYSE closed."""
    t = datetime(2026, 4, 3, 12, 0, 0, tzinfo=ET)
    assert WatchlistMonitor._is_market_open(t) is False


def test_market_closed_independence_day_observed():
    """Independence Day 2026 falls on Sat → observed Fri Jul 3 — NYSE closed."""
    t = datetime(2026, 7, 3, 12, 0, 0, tzinfo=ET)
    assert WatchlistMonitor._is_market_open(t) is False


def test_market_closed_thanksgiving():
    """Thanksgiving 2026 (Thu Nov 26) — NYSE closed."""
    t = datetime(2026, 11, 26, 12, 0, 0, tzinfo=ET)
    assert WatchlistMonitor._is_market_open(t) is False


def test_market_closed_christmas():
    """Christmas 2026 (Fri Dec 25) — NYSE closed."""
    t = datetime(2026, 12, 25, 12, 0, 0, tzinfo=ET)
    assert WatchlistMonitor._is_market_open(t) is False


def test_market_open_columbus_day():
    """Columbus Day 2026 (Mon Oct 12) — NYSE is OPEN (not an NYSE holiday)."""
    t = datetime(2026, 10, 12, 12, 0, 0, tzinfo=ET)
    assert WatchlistMonitor._is_market_open(t) is True


def test_market_open_veterans_day():
    """Veterans Day 2026 (Wed Nov 11) — NYSE is OPEN (not an NYSE holiday)."""
    t = datetime(2026, 11, 11, 12, 0, 0, tzinfo=ET)
    assert WatchlistMonitor._is_market_open(t) is True


def test_nyse_holidays_for_year_2026():
    """_nyse_holidays_for_year returns exactly 10 dates with expected entries."""
    holidays = _nyse_holidays_for_year(2026)
    assert len(holidays) == 10
    # Good Friday 2026 = April 3
    assert _dt.date(2026, 4, 3) in holidays
    # Juneteenth 2026 = June 19 (Friday)
    assert _dt.date(2026, 6, 19) in holidays
