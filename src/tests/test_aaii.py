"""Tests for AAII sentiment data module."""

import pytest
from unittest.mock import patch, MagicMock, PropertyMock
import pandas as pd

from bluehorseshoe.data.aaii import fetch_aaii_history, get_aaii_snapshot


# ---------------------------------------------------------------------------
# Sample data helpers
# ---------------------------------------------------------------------------

def _make_history(spreads, start_date="2026-01-01"):
    """Build AAII history rows with weekly dates and given bull-bear spreads.

    Each spread is converted to bullish/bearish percentages around a 50% midpoint.
    E.g., spread=10 → bullish=0.30, bearish=0.20, neutral=0.50
    """
    from datetime import datetime, timedelta
    base = datetime.strptime(start_date, "%Y-%m-%d")
    rows = []
    for i, sp in enumerate(spreads):
        d = (base + timedelta(weeks=i)).strftime("%Y-%m-%d")
        bullish = (50 + sp / 2) / 100.0  # decimal form
        bearish = (50 - sp / 2) / 100.0
        neutral = 1.0 - bullish - bearish
        rows.append({
            "date": d,
            "bullish": bullish,
            "bearish": bearish,
            "neutral": neutral,
            "bull_bear_spread": sp,
        })
    return rows


def _make_aaii_dataframe(n=10, percentage_format=False):
    """Create a DataFrame mimicking AAII/AAII_SENTIMENT from Nasdaq Data Link."""
    from datetime import datetime, timedelta
    dates = [datetime(2026, 1, 1) + timedelta(weeks=i) for i in range(n)]
    bullish_vals = [0.35 + 0.01 * i for i in range(n)]
    bearish_vals = [0.30 - 0.005 * i for i in range(n)]
    neutral_vals = [1.0 - b - br for b, br in zip(bullish_vals, bearish_vals)]

    if percentage_format:
        bullish_vals = [v * 100 for v in bullish_vals]
        bearish_vals = [v * 100 for v in bearish_vals]
        neutral_vals = [v * 100 for v in neutral_vals]

    return pd.DataFrame({
        "Date": dates,
        "Bullish": bullish_vals,
        "Bearish": bearish_vals,
        "Neutral": neutral_vals,
    })


# ---------------------------------------------------------------------------
# fetch_aaii_history tests
# ---------------------------------------------------------------------------

class TestFetchAaiiHistory:
    @patch("bluehorseshoe.data.aaii.get_settings")
    def test_api_fetch_success(self, mock_settings):
        """Successful fetch via Nasdaq Data Link API."""
        mock_settings.return_value = MagicMock(nasdaq_data_link_api_key="test-key")
        df = _make_aaii_dataframe(n=5)

        with patch.dict("sys.modules", {"nasdaqdatalink": MagicMock()}) as _:
            import sys
            mock_ndl = sys.modules["nasdaqdatalink"]
            mock_ndl.get.return_value = df

            result = fetch_aaii_history(weeks=52)
            assert len(result) == 5
            assert "date" in result[0]
            assert "bullish" in result[0]
            assert "bearish" in result[0]
            assert "bull_bear_spread" in result[0]
            # All values should be in decimal form (0-1)
            assert 0 <= result[0]["bullish"] <= 1
            assert 0 <= result[0]["bearish"] <= 1

    @patch("bluehorseshoe.data.aaii.requests.get")
    @patch("bluehorseshoe.data.aaii.get_settings")
    def test_excel_fallback(self, mock_settings, mock_get):
        """When no API key is set, falls back to Excel download."""
        mock_settings.return_value = MagicMock(nasdaq_data_link_api_key="")

        # Create a mock Excel response
        df = _make_aaii_dataframe(n=3)
        import io
        buf = io.BytesIO()
        df.to_excel(buf, index=False, engine="openpyxl")
        buf.seek(0)

        mock_resp = MagicMock()
        mock_resp.content = buf.read()
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = fetch_aaii_history(weeks=52)
        assert len(result) == 3
        assert "bull_bear_spread" in result[0]

    @patch("bluehorseshoe.data.aaii.requests.get")
    @patch("bluehorseshoe.data.aaii.get_settings")
    def test_both_fail_returns_empty(self, mock_settings, mock_get):
        """When both API and Excel fail, returns empty list."""
        mock_settings.return_value = MagicMock(nasdaq_data_link_api_key="")
        mock_get.side_effect = Exception("Network error")

        result = fetch_aaii_history()
        assert result == []

    @patch("bluehorseshoe.data.aaii.get_settings")
    def test_percentage_format_auto_detected(self, mock_settings):
        """Values > 1 are treated as percentages and converted to decimals."""
        mock_settings.return_value = MagicMock(nasdaq_data_link_api_key="test-key")
        df = _make_aaii_dataframe(n=3, percentage_format=True)

        with patch.dict("sys.modules", {"nasdaqdatalink": MagicMock()}) as _:
            import sys
            mock_ndl = sys.modules["nasdaqdatalink"]
            mock_ndl.get.return_value = df

            result = fetch_aaii_history(weeks=52)
            assert len(result) == 3
            # After normalization, all values should be decimal
            for row in result:
                assert 0 <= row["bullish"] <= 1
                assert 0 <= row["bearish"] <= 1


# ---------------------------------------------------------------------------
# get_aaii_snapshot tests
# ---------------------------------------------------------------------------

class TestGetAaiiSnapshot:
    @patch("bluehorseshoe.data.aaii.fetch_aaii_history")
    def test_snapshot_exact_date(self, mock_fetch):
        """Finds the row matching the exact target date."""
        mock_fetch.return_value = _make_history([5, 10, 15], "2026-03-01")
        result = get_aaii_snapshot("2026-03-15")  # Third week
        assert result is not None
        assert result["bull_bear_spread"] == 15

    @patch("bluehorseshoe.data.aaii.fetch_aaii_history")
    def test_snapshot_fallback_to_previous(self, mock_fetch):
        """When target_date falls between surveys, use most recent prior."""
        mock_fetch.return_value = _make_history([5, 10, 15], "2026-03-01")
        # 2026-03-10 is between week 1 (03-01) and week 2 (03-08)
        result = get_aaii_snapshot("2026-03-10")
        assert result is not None
        assert result["bull_bear_spread"] == 10  # 2026-03-08 row

    @patch("bluehorseshoe.data.aaii.fetch_aaii_history")
    def test_snapshot_no_data_returns_none(self, mock_fetch):
        """Empty history returns None."""
        mock_fetch.return_value = []
        assert get_aaii_snapshot("2026-03-15") is None

    @patch("bluehorseshoe.data.aaii.fetch_aaii_history")
    def test_snapshot_date_before_history(self, mock_fetch):
        """Target date before all history returns None."""
        mock_fetch.return_value = _make_history([5, 10], "2026-03-01")
        assert get_aaii_snapshot("2026-02-28") is None

    @patch("bluehorseshoe.data.aaii.fetch_aaii_history")
    def test_signal_extreme_bullish(self, mock_fetch):
        mock_fetch.return_value = _make_history([30], "2026-03-01")
        result = get_aaii_snapshot("2026-03-01")
        assert result["signal"] == "Extreme Bullish"

    @patch("bluehorseshoe.data.aaii.fetch_aaii_history")
    def test_signal_bullish(self, mock_fetch):
        mock_fetch.return_value = _make_history([15], "2026-03-01")
        result = get_aaii_snapshot("2026-03-01")
        assert result["signal"] == "Bullish"

    @patch("bluehorseshoe.data.aaii.fetch_aaii_history")
    def test_signal_neutral(self, mock_fetch):
        mock_fetch.return_value = _make_history([5], "2026-03-01")
        result = get_aaii_snapshot("2026-03-01")
        assert result["signal"] == "Neutral"

    @patch("bluehorseshoe.data.aaii.fetch_aaii_history")
    def test_signal_bearish(self, mock_fetch):
        mock_fetch.return_value = _make_history([-15], "2026-03-01")
        result = get_aaii_snapshot("2026-03-01")
        assert result["signal"] == "Bearish"

    @patch("bluehorseshoe.data.aaii.fetch_aaii_history")
    def test_signal_extreme_bearish(self, mock_fetch):
        mock_fetch.return_value = _make_history([-30], "2026-03-01")
        result = get_aaii_snapshot("2026-03-01")
        assert result["signal"] == "Extreme Bearish"

    @patch("bluehorseshoe.data.aaii.fetch_aaii_history")
    def test_spread_normalization_and_clamping(self, mock_fetch):
        """spread_normalized = spread / 50, clamped to [-1, 1]."""
        # Spread of 25 → 25/50 = 0.5
        mock_fetch.return_value = _make_history([25], "2026-03-01")
        result = get_aaii_snapshot("2026-03-01")
        assert result["spread_normalized"] == pytest.approx(0.5, abs=0.01)

        # Extreme spread of 60 → 60/50 = 1.2, clamped to 1.0
        mock_fetch.return_value = _make_history([60], "2026-03-01")
        result = get_aaii_snapshot("2026-03-01")
        assert result["spread_normalized"] == 1.0

        # Extreme negative spread of -60 → -60/50 = -1.2, clamped to -1.0
        mock_fetch.return_value = _make_history([-60], "2026-03-01")
        result = get_aaii_snapshot("2026-03-01")
        assert result["spread_normalized"] == -1.0

    @patch("bluehorseshoe.data.aaii.fetch_aaii_history")
    def test_eight_week_average(self, mock_fetch):
        """8-week average of spread values."""
        spreads = [10, 20, 10, 20, 10, 20, 10, 20]  # avg = 15
        mock_fetch.return_value = _make_history(spreads, "2026-01-01")
        result = get_aaii_snapshot("2026-02-19")  # Last week
        assert result["spread_8w_avg"] == pytest.approx(15.0, abs=0.01)

    @patch("bluehorseshoe.data.aaii.fetch_aaii_history")
    def test_percentile_calculation(self, mock_fetch):
        """With spreads [5, 10, 15, 20, 25], value 25 → 5/5 = 100th percentile."""
        spreads = [5, 10, 15, 20, 25]
        mock_fetch.return_value = _make_history(spreads, "2026-01-01")
        result = get_aaii_snapshot("2026-01-29")  # spread=25, window=[5,10,15,20,25]
        assert result["percentile_52w"] == 100.0

        # spread=15, window=[5,10,15,20,25] → 3/5 = 60th percentile
        # Query the last date so all 5 weeks are in the window but target the 3rd spread
        spreads2 = [25, 20, 15, 10, 5]  # spread=5 is last
        mock_fetch.return_value = _make_history(spreads2, "2026-01-01")
        result2 = get_aaii_snapshot("2026-01-29")  # spread=5, window=[5,10,15,20,25] sorted
        # Values <= 5: just 1. Percentile = 1/5 = 20%
        assert result2["percentile_52w"] == pytest.approx(20.0, abs=0.1)
