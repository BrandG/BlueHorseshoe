"""Tests for ProviderPool dispatcher."""
from unittest.mock import MagicMock, patch
import pytest

from bluehorseshoe.data.providers.base import DataProvider, ProviderConfig
from bluehorseshoe.data.provider_pool import ProviderPool, create_provider_pool_from_env


class FakeProvider(DataProvider):
    """Simple test double for DataProvider."""
    def __init__(self, name, cps=2, priority=0, available=True, fetch_result=None):
        super().__init__(ProviderConfig(
            name=name, cps=cps, priority=priority, enabled=True))
        self._available = available
        self._fetch_result = fetch_result

    def fetch(self, symbol, recent=False):
        if callable(self._fetch_result):
            return self._fetch_result(symbol, recent)
        return self._fetch_result

    def is_available(self):
        return self._available


class TestProviderPool:
    def test_partition_proportional_to_cps(self):
        """2 providers at 5+2 CPS, 1000 symbols → ~714 / 286 split."""
        p1 = FakeProvider("tiingo", cps=5, priority=0)
        p2 = FakeProvider("yahoo", cps=2, priority=1)
        pool = ProviderPool([p1, p2])

        symbols = [f"SYM{i}" for i in range(1000)]
        assignments = pool.partition_symbols(symbols)

        assert len(assignments["tiingo"]) == 714  # floor(1000 * 5/7)
        assert len(assignments["yahoo"]) == 286   # remaining
        # No overlap, no loss
        all_assigned = assignments["tiingo"] + assignments["yahoo"]
        assert len(all_assigned) == 1000
        assert set(all_assigned) == set(symbols)

    def test_partition_three_providers(self):
        """3 providers: 5+2+1 = 8 CPS total."""
        p1 = FakeProvider("tiingo", cps=5, priority=0)
        p2 = FakeProvider("yahoo", cps=2, priority=1)
        p3 = FakeProvider("av", cps=1, priority=2)
        pool = ProviderPool([p1, p2, p3])

        symbols = [f"S{i}" for i in range(800)]
        assignments = pool.partition_symbols(symbols)

        assert len(assignments["tiingo"]) == 500  # floor(800*5/8)
        assert len(assignments["yahoo"]) == 200   # floor(800*2/8)
        assert len(assignments["av"]) == 100       # remaining
        total = sum(len(v) for v in assignments.values())
        assert total == 800

    def test_single_provider_gets_all(self):
        """Pool with 1 provider assigns all symbols to it."""
        p1 = FakeProvider("tiingo", cps=5)
        pool = ProviderPool([p1])

        symbols = ["AAPL", "MSFT", "GOOGL"]
        assignments = pool.partition_symbols(symbols)
        assert assignments["tiingo"] == symbols

    def test_fetch_single_tries_priority_order(self):
        """fetch_single tries providers in priority order."""
        calls = []

        def p1_fetch(sym, recent):
            calls.append(("p1", sym))
            return None  # Fail

        def p2_fetch(sym, recent):
            calls.append(("p2", sym))
            return {"name": sym, "days": []}

        p1 = FakeProvider("tiingo", cps=5, priority=0, fetch_result=p1_fetch)
        p2 = FakeProvider("yahoo", cps=2, priority=1, fetch_result=p2_fetch)
        pool = ProviderPool([p2, p1])  # Intentionally out of order

        result = pool.fetch_single("AAPL")
        assert result is not None
        # p1 (priority 0) tried first, then p2 (priority 1)
        assert calls == [("p1", "AAPL"), ("p2", "AAPL")]

    def test_fetch_single_returns_first_success(self):
        """fetch_single returns on first successful provider."""
        data = {"name": "AAPL", "days": [{"date": "2024-01-03"}]}
        p1 = FakeProvider("tiingo", cps=5, priority=0, fetch_result=data)
        p2 = FakeProvider("yahoo", cps=2, priority=1, fetch_result=None)
        pool = ProviderPool([p1, p2])

        result = pool.fetch_single("AAPL")
        assert result == data

    def test_fetch_single_all_fail_returns_none(self):
        p1 = FakeProvider("tiingo", cps=5, priority=0, fetch_result=None)
        p2 = FakeProvider("yahoo", cps=2, priority=1, fetch_result=None)
        pool = ProviderPool([p1, p2])

        result = pool.fetch_single("AAPL")
        assert result is None

    def test_unavailable_provider_excluded(self):
        p1 = FakeProvider("tiingo", cps=5, priority=0, available=True)
        p2 = FakeProvider("yahoo", cps=2, priority=1, available=False)
        pool = ProviderPool([p1, p2])

        assert len(pool.providers) == 1
        assert pool.providers[0].name == "tiingo"
        assert pool.total_cps == 5

    def test_no_providers_raises(self):
        with pytest.raises(ValueError, match="No data providers"):
            ProviderPool([])

    def test_no_available_providers_raises(self):
        p1 = FakeProvider("tiingo", available=False)
        with pytest.raises(ValueError, match="No data providers"):
            ProviderPool([p1])

    def test_get_provider_by_name(self):
        p1 = FakeProvider("tiingo", cps=5, priority=0)
        p2 = FakeProvider("yahoo", cps=2, priority=1)
        pool = ProviderPool([p1, p2])

        assert pool.get_provider_by_name("tiingo") is p1
        assert pool.get_provider_by_name("yahoo") is p2
        assert pool.get_provider_by_name("nonexistent") is None


class TestCreateProviderPoolFromEnv:
    @patch('bluehorseshoe.data.provider_pool.get_settings')
    def test_tiingo_only(self, mock_settings):
        mock_settings.return_value = MagicMock(
            tiingo_api_key="key123",
            tiingo_cps=5,
            yahoo_enabled=False,
            alphavantage_data_enabled=False,
            alphavantage_key="",
            alphavantage_cps=1,
            provider_max_retries=1,
        )
        pool = create_provider_pool_from_env()
        assert len(pool.providers) == 1
        assert pool.providers[0].name == "tiingo"

    @patch('bluehorseshoe.data.provider_pool.get_settings')
    def test_all_three_providers(self, mock_settings):
        mock_settings.return_value = MagicMock(
            tiingo_api_key="tkey",
            tiingo_cps=5,
            yahoo_enabled=True,
            yahoo_cps=2,
            alphavantage_data_enabled=True,
            alphavantage_key="akey",
            alphavantage_cps=1,
            provider_max_retries=1,
        )
        pool = create_provider_pool_from_env()
        assert len(pool.providers) == 3
        names = [p.name for p in pool.providers]
        assert names == ["tiingo", "yahoo", "alphavantage"]  # Sorted by priority
        assert pool.total_cps == 8

    @patch('bluehorseshoe.data.provider_pool.get_settings')
    def test_no_providers_raises(self, mock_settings):
        mock_settings.return_value = MagicMock(
            tiingo_api_key="",
            yahoo_enabled=False,
            alphavantage_data_enabled=False,
            alphavantage_key="",
            alphavantage_cps=1,
            provider_max_retries=1,
        )
        with pytest.raises(ValueError, match="No data providers configured"):
            create_provider_pool_from_env()

    @patch('bluehorseshoe.data.provider_pool.get_settings')
    def test_yahoo_only(self, mock_settings):
        mock_settings.return_value = MagicMock(
            tiingo_api_key="",
            yahoo_enabled=True,
            yahoo_cps=2,
            alphavantage_data_enabled=False,
            alphavantage_key="",
            alphavantage_cps=1,
            provider_max_retries=1,
        )
        pool = create_provider_pool_from_env()
        assert len(pool.providers) == 1
        assert pool.providers[0].name == "yahoo"
