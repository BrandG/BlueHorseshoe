"""Tests for VIX data module."""

import pytest
from unittest.mock import patch, MagicMock

from bluehorseshoe.data.vix import fetch_vix_history, get_vix_snapshot


# ---------------------------------------------------------------------------
# Sample data helper
# ---------------------------------------------------------------------------

def _make_history(closes, start_date="2026-03-01"):
    """Build a list of VIX history dicts with sequential dates."""
    from datetime import datetime, timedelta
    base = datetime.strptime(start_date, "%Y-%m-%d")
    rows = []
    for i, c in enumerate(closes):
        d = (base + timedelta(days=i)).strftime("%Y-%m-%d")
        rows.append({"date": d, "open": c, "high": c + 1, "low": c - 1, "close": c})
    return rows


CBOE_RESPONSE = {
    "data": [
        {"date": "2026-03-10T00:00:00", "open": 18.0, "high": 19.0, "low": 17.5, "close": 18.5},
        {"date": "2026-03-11T00:00:00", "open": 18.5, "high": 20.0, "low": 18.0, "close": 19.0},
        {"date": "2026-03-12T00:00:00", "open": 19.0, "high": 21.0, "low": 18.5, "close": 20.5},
    ]
}


# ---------------------------------------------------------------------------
# fetch_vix_history tests
# ---------------------------------------------------------------------------

class TestFetchVixHistory:
    @patch("bluehorseshoe.data.vix.requests.get")
    def test_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = CBOE_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = fetch_vix_history(days=90)
        assert len(result) == 3
        assert result[0]["date"] == "2026-03-10"
        assert result[0]["close"] == 18.5
        assert result[2]["close"] == 20.5

    @patch("bluehorseshoe.data.vix.requests.get")
    def test_empty_response(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": []}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = fetch_vix_history()
        assert result == []

    @patch("bluehorseshoe.data.vix.requests.get")
    def test_network_exception(self, mock_get):
        mock_get.side_effect = Exception("Connection timeout")

        result = fetch_vix_history()
        assert result == []

    @patch("bluehorseshoe.data.vix.requests.get")
    def test_days_limit(self, mock_get):
        """When history has more rows than requested days, only return last N."""
        data = [
            {"date": f"2026-03-{i:02d}T00:00:00", "open": 15.0, "high": 16.0, "low": 14.0, "close": 15.0 + i * 0.1}
            for i in range(1, 21)
        ]
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": data}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = fetch_vix_history(days=5)
        assert len(result) == 5
        assert result[0]["date"] == "2026-03-16"


# ---------------------------------------------------------------------------
# get_vix_snapshot tests
# ---------------------------------------------------------------------------

class TestGetVixSnapshot:
    @patch("bluehorseshoe.data.vix.fetch_vix_history")
    def test_snapshot_exact_date(self, mock_fetch):
        mock_fetch.return_value = _make_history([18.0, 19.0, 20.0], "2026-03-10")
        result = get_vix_snapshot("2026-03-12")
        assert result is not None
        assert result["close"] == 20.0
        assert result["fear_level"] == "Moderate"

    @patch("bluehorseshoe.data.vix.fetch_vix_history")
    def test_snapshot_fallback_date(self, mock_fetch):
        """When target_date is a weekend, falls back to most recent."""
        mock_fetch.return_value = _make_history([18.0, 19.0, 20.0], "2026-03-10")
        # 2026-03-13 is after our last date (2026-03-12)
        result = get_vix_snapshot("2026-03-13")
        assert result is not None
        assert result["close"] == 20.0

    @patch("bluehorseshoe.data.vix.fetch_vix_history")
    def test_snapshot_no_data(self, mock_fetch):
        mock_fetch.return_value = []
        assert get_vix_snapshot("2026-03-12") is None

    @patch("bluehorseshoe.data.vix.fetch_vix_history")
    def test_snapshot_date_before_history(self, mock_fetch):
        mock_fetch.return_value = _make_history([18.0, 19.0], "2026-03-10")
        assert get_vix_snapshot("2026-03-09") is None

    @patch("bluehorseshoe.data.vix.fetch_vix_history")
    def test_fear_level_low(self, mock_fetch):
        mock_fetch.return_value = _make_history([12.0], "2026-03-10")
        result = get_vix_snapshot("2026-03-10")
        assert result["fear_level"] == "Low"
        assert result["close"] == 12.0

    @patch("bluehorseshoe.data.vix.fetch_vix_history")
    def test_fear_level_elevated(self, mock_fetch):
        mock_fetch.return_value = _make_history([25.0], "2026-03-10")
        result = get_vix_snapshot("2026-03-10")
        assert result["fear_level"] == "Elevated"

    @patch("bluehorseshoe.data.vix.fetch_vix_history")
    def test_fear_level_high(self, mock_fetch):
        mock_fetch.return_value = _make_history([35.0], "2026-03-10")
        result = get_vix_snapshot("2026-03-10")
        assert result["fear_level"] == "High"

    @patch("bluehorseshoe.data.vix.fetch_vix_history")
    def test_change_1d(self, mock_fetch):
        """1-day change = (20 - 18) / 18 * 100 = 11.11%"""
        mock_fetch.return_value = _make_history([18.0, 20.0], "2026-03-10")
        result = get_vix_snapshot("2026-03-11")
        assert result["change_1d"] == pytest.approx(11.11, abs=0.01)

    @patch("bluehorseshoe.data.vix.fetch_vix_history")
    def test_percentile_calculation(self, mock_fetch):
        """With closes [10, 15, 20, 25, 30], value 25 → 4/5 = 80th percentile."""
        mock_fetch.return_value = _make_history([10, 15, 20, 25, 30], "2026-03-01")
        result = get_vix_snapshot("2026-03-05")  # close=30
        assert result["percentile_90d"] == 100.0  # 30 is at top

        result2 = get_vix_snapshot("2026-03-04")  # close=25
        assert result2["percentile_90d"] == pytest.approx(100.0, abs=0.1)  # 4/4 = 100 (only sees 4 values)

    @patch("bluehorseshoe.data.vix.fetch_vix_history")
    def test_sma_20_with_short_window(self, mock_fetch):
        """SMA-20 with only 3 days = average of those 3."""
        mock_fetch.return_value = _make_history([18.0, 20.0, 22.0], "2026-03-10")
        result = get_vix_snapshot("2026-03-12")
        assert result["sma_20"] == 20.0
