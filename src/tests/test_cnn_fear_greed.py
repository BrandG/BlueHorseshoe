"""Tests for CNN Fear & Greed data module."""

import pytest
from unittest.mock import patch, MagicMock

from bluehorseshoe.data.cnn_fear_greed import fetch_cnn_history, get_cnn_snapshot, _classify_rating


# ---------------------------------------------------------------------------
# Sample data helper
# ---------------------------------------------------------------------------

def _make_history(scores, start_date="2026-03-01"):
    """Build a list of CNN F&G history dicts with sequential dates."""
    from datetime import datetime, timedelta
    base = datetime.strptime(start_date, "%Y-%m-%d")
    rows = []
    for i, s in enumerate(scores):
        d = (base + timedelta(days=i)).strftime("%Y-%m-%d")
        rows.append({"date": d, "score": s})
    return rows


def _make_api_response(scores, start_date="2026-03-01"):
    """Build a mock CNN API response with historical data points."""
    from datetime import datetime, timedelta
    base = datetime.strptime(start_date, "%Y-%m-%d")
    data = []
    for i, s in enumerate(scores):
        dt = base + timedelta(days=i)
        ts_ms = int(dt.timestamp() * 1000)
        data.append({"x": ts_ms, "y": s})
    return {
        "fear_and_greed": {"score": scores[-1] if scores else 50, "rating": "Neutral"},
        "fear_and_greed_historical": {"data": data},
    }


CNN_API_RESPONSE = _make_api_response([45.0, 48.0, 52.0], "2026-03-10")


# ---------------------------------------------------------------------------
# fetch_cnn_history tests
# ---------------------------------------------------------------------------

class TestFetchCnnHistory:
    @patch("bluehorseshoe.data.cnn_fear_greed.requests.get")
    def test_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = CNN_API_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = fetch_cnn_history(days=90)
        assert len(result) == 3
        assert result[0]["date"] == "2026-03-10"
        assert result[0]["score"] == 45.0
        assert result[2]["score"] == 52.0

    @patch("bluehorseshoe.data.cnn_fear_greed.requests.get")
    def test_empty_response(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"fear_and_greed_historical": {"data": []}}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = fetch_cnn_history()
        assert result == []

    @patch("bluehorseshoe.data.cnn_fear_greed.requests.get")
    def test_missing_historical_key(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"fear_and_greed": {"score": 50}}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = fetch_cnn_history()
        assert result == []

    @patch("bluehorseshoe.data.cnn_fear_greed.requests.get")
    def test_network_exception(self, mock_get):
        mock_get.side_effect = Exception("Connection timeout")

        result = fetch_cnn_history()
        assert result == []

    @patch("bluehorseshoe.data.cnn_fear_greed.requests.get")
    def test_days_limit(self, mock_get):
        """When history has more rows than requested days, only return last N."""
        scores = [50.0 + i for i in range(20)]
        response = _make_api_response(scores, "2026-03-01")
        mock_resp = MagicMock()
        mock_resp.json.return_value = response
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = fetch_cnn_history(days=5)
        assert len(result) == 5
        assert result[0]["date"] == "2026-03-16"


# ---------------------------------------------------------------------------
# get_cnn_snapshot tests
# ---------------------------------------------------------------------------

class TestGetCnnSnapshot:
    @patch("bluehorseshoe.data.cnn_fear_greed.fetch_cnn_history")
    def test_snapshot_exact_date(self, mock_fetch):
        mock_fetch.return_value = _make_history([30.0, 35.0, 40.0], "2026-03-10")
        result = get_cnn_snapshot("2026-03-12")
        assert result is not None
        assert result["score"] == 40.0
        assert result["rating"] == "Fear"

    @patch("bluehorseshoe.data.cnn_fear_greed.fetch_cnn_history")
    def test_snapshot_fallback_date(self, mock_fetch):
        """When target_date is after last data, falls back to most recent."""
        mock_fetch.return_value = _make_history([30.0, 35.0, 40.0], "2026-03-10")
        result = get_cnn_snapshot("2026-03-13")
        assert result is not None
        assert result["score"] == 40.0

    @patch("bluehorseshoe.data.cnn_fear_greed.fetch_cnn_history")
    def test_snapshot_no_data(self, mock_fetch):
        mock_fetch.return_value = []
        assert get_cnn_snapshot("2026-03-12") is None

    @patch("bluehorseshoe.data.cnn_fear_greed.fetch_cnn_history")
    def test_snapshot_date_before_history(self, mock_fetch):
        mock_fetch.return_value = _make_history([30.0, 35.0], "2026-03-10")
        assert get_cnn_snapshot("2026-03-09") is None

    @patch("bluehorseshoe.data.cnn_fear_greed.fetch_cnn_history")
    def test_rating_extreme_fear(self, mock_fetch):
        mock_fetch.return_value = _make_history([10.0], "2026-03-10")
        result = get_cnn_snapshot("2026-03-10")
        assert result["rating"] == "Extreme Fear"

    @patch("bluehorseshoe.data.cnn_fear_greed.fetch_cnn_history")
    def test_rating_fear(self, mock_fetch):
        mock_fetch.return_value = _make_history([35.0], "2026-03-10")
        result = get_cnn_snapshot("2026-03-10")
        assert result["rating"] == "Fear"

    @patch("bluehorseshoe.data.cnn_fear_greed.fetch_cnn_history")
    def test_rating_neutral(self, mock_fetch):
        mock_fetch.return_value = _make_history([50.0], "2026-03-10")
        result = get_cnn_snapshot("2026-03-10")
        assert result["rating"] == "Neutral"

    @patch("bluehorseshoe.data.cnn_fear_greed.fetch_cnn_history")
    def test_rating_greed(self, mock_fetch):
        mock_fetch.return_value = _make_history([65.0], "2026-03-10")
        result = get_cnn_snapshot("2026-03-10")
        assert result["rating"] == "Greed"

    @patch("bluehorseshoe.data.cnn_fear_greed.fetch_cnn_history")
    def test_rating_extreme_greed(self, mock_fetch):
        mock_fetch.return_value = _make_history([85.0], "2026-03-10")
        result = get_cnn_snapshot("2026-03-10")
        assert result["rating"] == "Extreme Greed"

    @patch("bluehorseshoe.data.cnn_fear_greed.fetch_cnn_history")
    def test_change_1d(self, mock_fetch):
        """1-day change = (40 - 30) / 30 * 100 = 33.33%"""
        mock_fetch.return_value = _make_history([30.0, 40.0], "2026-03-10")
        result = get_cnn_snapshot("2026-03-11")
        assert result["change_1d"] == pytest.approx(33.33, abs=0.01)

    @patch("bluehorseshoe.data.cnn_fear_greed.fetch_cnn_history")
    def test_percentile_calculation(self, mock_fetch):
        """With scores [10, 20, 30, 40, 50], value 50 → 5/5 = 100th percentile."""
        mock_fetch.return_value = _make_history([10, 20, 30, 40, 50], "2026-03-01")
        result = get_cnn_snapshot("2026-03-05")  # score=50
        assert result["percentile_90d"] == 100.0

        result2 = get_cnn_snapshot("2026-03-04")  # score=40
        assert result2["percentile_90d"] == pytest.approx(100.0, abs=0.1)  # 4/4 = 100

    @patch("bluehorseshoe.data.cnn_fear_greed.fetch_cnn_history")
    def test_sma_20_with_short_window(self, mock_fetch):
        """SMA-20 with only 3 days = average of those 3."""
        mock_fetch.return_value = _make_history([30.0, 40.0, 50.0], "2026-03-10")
        result = get_cnn_snapshot("2026-03-12")
        assert result["sma_20"] == 40.0


# ---------------------------------------------------------------------------
# _classify_rating unit tests
# ---------------------------------------------------------------------------

class TestClassifyRating:
    def test_boundary_extreme_fear(self):
        assert _classify_rating(0) == "Extreme Fear"
        assert _classify_rating(24) == "Extreme Fear"

    def test_boundary_fear(self):
        assert _classify_rating(25) == "Fear"
        assert _classify_rating(44) == "Fear"

    def test_boundary_neutral(self):
        assert _classify_rating(45) == "Neutral"
        assert _classify_rating(55) == "Neutral"

    def test_boundary_greed(self):
        assert _classify_rating(56) == "Greed"
        assert _classify_rating(74) == "Greed"

    def test_boundary_extreme_greed(self):
        assert _classify_rating(75) == "Extreme Greed"
        assert _classify_rating(100) == "Extreme Greed"
