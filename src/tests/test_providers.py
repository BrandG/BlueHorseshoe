"""Tests for individual data providers."""
from unittest.mock import patch, MagicMock, PropertyMock
import pandas as pd
import pytest

from bluehorseshoe.data.providers.base import ProviderConfig
from bluehorseshoe.data.providers.tiingo import TiingoProvider
from bluehorseshoe.data.providers.yahoo import YahooProvider
from bluehorseshoe.data.providers.alphavantage import AlphaVantageProvider


# ---------------------------------------------------------------------------
# TiingoProvider
# ---------------------------------------------------------------------------

class TestTiingoProvider:
    def _make_provider(self, cps=2, api_key="test-key"):
        return TiingoProvider(ProviderConfig(
            name="tiingo", api_key=api_key, cps=cps))

    @patch('bluehorseshoe.data.providers.tiingo.requests.get')
    def test_fetch_recent(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {
                'date': '2024-01-03T00:00:00+00:00',
                'adjOpen': 100.0, 'adjHigh': 110.0,
                'adjLow': 90.0, 'adjClose': 105.0, 'adjVolume': 1000
            }
        ]
        mock_get.return_value = mock_resp

        provider = self._make_provider()
        result = provider.fetch('AAPL', recent=True)
        assert result is not None
        assert result['name'] == 'AAPL'
        assert len(result['days']) == 1
        assert result['days'][0]['date'] == '2024-01-03'
        assert result['days'][0]['open'] == 100.0
        assert result['days'][0]['close'] == 105.0
        assert result['days'][0]['volume'] == 1000
        assert result['days'][0]['midpoint'] == round((100.0 + 105.0) / 2, 4)

    @patch('bluehorseshoe.data.providers.tiingo.requests.get')
    def test_fetch_adj_fallback(self, mock_get):
        """Falls back to non-adjusted fields when adj* are missing."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {
                'date': '2024-01-03T00:00:00+00:00',
                'open': 100.0, 'high': 110.0,
                'low': 90.0, 'close': 105.0, 'volume': 1000
            }
        ]
        mock_get.return_value = mock_resp

        provider = self._make_provider()
        result = provider.fetch('AAPL', recent=True)
        assert result is not None
        assert result['days'][0]['open'] == 100.0

    @patch('bluehorseshoe.data.providers.tiingo.requests.get')
    def test_404_returns_none(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        provider = self._make_provider()
        result = provider.fetch('INVALID')
        assert result is None

    @patch('bluehorseshoe.data.providers.tiingo.requests.get')
    def test_429_returns_none(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_get.return_value = mock_resp

        provider = self._make_provider()
        result = provider.fetch('AAPL')
        assert result is None

    @patch('bluehorseshoe.data.providers.tiingo.requests.get')
    def test_empty_response_returns_none(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        mock_get.return_value = mock_resp

        provider = self._make_provider()
        result = provider.fetch('AAPL')
        assert result is None

    def test_is_available_with_key(self):
        provider = self._make_provider(api_key="my-key")
        assert provider.is_available() is True

    def test_is_available_without_key(self):
        provider = self._make_provider(api_key="")
        assert provider.is_available() is False


# ---------------------------------------------------------------------------
# YahooProvider
# ---------------------------------------------------------------------------

class TestYahooProvider:
    def _make_provider(self, cps=2):
        return YahooProvider(ProviderConfig(name="yahoo", cps=cps))

    @patch('bluehorseshoe.data.providers.yahoo.yf.Ticker')
    def test_fetch_recent(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        df = pd.DataFrame({
            'Open': [100.0], 'High': [110.0], 'Low': [90.0],
            'Close': [105.0], 'Volume': [1000]
        }, index=pd.DatetimeIndex(['2024-01-03']))
        mock_ticker.history.return_value = df
        mock_ticker_cls.return_value = mock_ticker

        provider = self._make_provider()
        result = provider.fetch('AAPL', recent=True)
        assert result is not None
        assert result['name'] == 'AAPL'
        assert len(result['days']) == 1
        assert result['days'][0]['date'] == '2024-01-03'
        assert result['days'][0]['open'] == 100.0
        assert result['days'][0]['close'] == 105.0
        assert result['days'][0]['volume'] == 1000
        assert result['days'][0]['midpoint'] == round((100.0 + 105.0) / 2, 4)
        mock_ticker.history.assert_called_once_with(period="6mo")

    @patch('bluehorseshoe.data.providers.yahoo.yf.Ticker')
    def test_fetch_full(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        df = pd.DataFrame({
            'Open': [50.0], 'High': [55.0], 'Low': [45.0],
            'Close': [52.0], 'Volume': [500]
        }, index=pd.DatetimeIndex(['2020-01-02']))
        mock_ticker.history.return_value = df
        mock_ticker_cls.return_value = mock_ticker

        provider = self._make_provider()
        result = provider.fetch('AAPL', recent=False)
        assert result is not None
        mock_ticker.history.assert_called_once_with(start="2000-01-01")

    @patch('bluehorseshoe.data.providers.yahoo.yf.Ticker')
    def test_empty_dataframe_returns_none(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()
        mock_ticker_cls.return_value = mock_ticker

        provider = self._make_provider()
        result = provider.fetch('INVALID')
        assert result is None

    @patch('bluehorseshoe.data.providers.yahoo.yf.Ticker')
    def test_exception_returns_none(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = Exception("network error")
        mock_ticker_cls.return_value = mock_ticker

        provider = self._make_provider()
        result = provider.fetch('AAPL')
        assert result is None

    def test_is_available_always_true(self):
        provider = self._make_provider()
        assert provider.is_available() is True


# ---------------------------------------------------------------------------
# AlphaVantageProvider
# ---------------------------------------------------------------------------

class TestAlphaVantageProvider:
    def _make_provider(self, cps=2, api_key="test-key"):
        return AlphaVantageProvider(ProviderConfig(
            name="alphavantage", api_key=api_key, cps=cps))

    @patch('bluehorseshoe.data.providers.alphavantage.requests.get')
    def test_fetch_compact(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "Time Series (Daily)": {
                "2024-01-03": {
                    "1. open": "100.0", "2. high": "110.0",
                    "3. low": "90.0", "4. close": "107.0",
                    "5. adjusted close": "105.0", "6. volume": "1000"
                },
                "2024-01-02": {
                    "1. open": "98.0", "2. high": "108.0",
                    "3. low": "88.0", "4. close": "103.0",
                    "5. adjusted close": "101.0", "6. volume": "900"
                }
            }
        }
        mock_get.return_value = mock_resp

        provider = self._make_provider()
        result = provider.fetch('AAPL', recent=True)
        assert result is not None
        assert result['name'] == 'AAPL'
        assert len(result['days']) == 2
        # Oldest first (sorted)
        assert result['days'][0]['date'] == '2024-01-02'
        assert result['days'][1]['date'] == '2024-01-03'
        # Uses adjusted close
        assert result['days'][1]['close'] == 105.0
        assert result['days'][1]['midpoint'] == round((100.0 + 105.0) / 2, 4)

        # Verify compact outputsize for recent=True
        call_kwargs = mock_get.call_args
        assert call_kwargs[1]['params']['outputsize'] == 'compact'

    @patch('bluehorseshoe.data.providers.alphavantage.requests.get')
    def test_fetch_full(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "Time Series (Daily)": {
                "2024-01-02": {
                    "1. open": "98.0", "2. high": "108.0",
                    "3. low": "88.0", "4. close": "103.0",
                    "5. adjusted close": "101.0", "6. volume": "900"
                }
            }
        }
        mock_get.return_value = mock_resp

        provider = self._make_provider()
        result = provider.fetch('AAPL', recent=False)
        assert result is not None
        call_kwargs = mock_get.call_args
        assert call_kwargs[1]['params']['outputsize'] == 'full'

    @patch('bluehorseshoe.data.providers.alphavantage.requests.get')
    def test_missing_time_series_returns_none(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"Error Message": "Invalid API call"}
        mock_get.return_value = mock_resp

        provider = self._make_provider()
        result = provider.fetch('INVALID')
        assert result is None

    @patch('bluehorseshoe.data.providers.alphavantage.requests.get')
    def test_exception_returns_none(self, mock_get):
        mock_get.side_effect = Exception("timeout")

        provider = self._make_provider()
        result = provider.fetch('AAPL')
        assert result is None

    def test_is_available_with_key(self):
        provider = self._make_provider(api_key="my-key")
        assert provider.is_available() is True

    def test_is_available_without_key(self):
        provider = self._make_provider(api_key="")
        assert provider.is_available() is False
