"""Provider pool for dispatching symbol fetches across multiple data providers."""
import logging
import math
from typing import List, Dict, Optional

from bluehorseshoe.core.config import get_settings
from bluehorseshoe.data.providers.base import DataProvider, ProviderConfig
from bluehorseshoe.data.providers.tiingo import TiingoProvider
from bluehorseshoe.data.providers.yahoo import YahooProvider
from bluehorseshoe.data.providers.alphavantage import AlphaVantageProvider


class ProviderPool:
    """Manages multiple data providers with capacity-weighted dispatch and fallback."""

    def __init__(self, providers: List[DataProvider], max_retries: int = 1):
        self.providers = [p for p in providers
                          if p.config.enabled and p.is_available()]
        self.providers.sort(key=lambda p: p.config.priority)
        self.total_cps = sum(p.config.cps for p in self.providers)
        self.max_retries = max_retries

        if not self.providers:
            raise ValueError("No data providers are configured and available")

    def partition_symbols(self, symbols: List[str]) -> Dict[str, List[str]]:
        """Split symbols proportional to each provider's CPS capacity.

        Example: Tiingo@5 + Yahoo@2 = 7 total → Tiingo gets 71%, Yahoo 29%.
        """
        assignments: Dict[str, List[str]] = {}
        remaining = list(symbols)

        for i, provider in enumerate(self.providers):
            if i == len(self.providers) - 1:
                # Last provider gets all remaining
                assignments[provider.name] = remaining
            else:
                share = math.floor(
                    len(symbols) * provider.config.cps / self.total_cps
                )
                assignments[provider.name] = remaining[:share]
                remaining = remaining[share:]

        return assignments

    def fetch_single(self, symbol: str, recent: bool = False) -> Optional[Dict]:
        """Try providers in priority order until one succeeds."""
        for provider in self.providers:
            data = provider.fetch(symbol, recent=recent)
            if data is not None:
                return data
        return None

    def get_provider_by_name(self, name: str) -> Optional[DataProvider]:
        """Look up a provider by name."""
        for p in self.providers:
            if p.name == name:
                return p
        return None


def create_provider_pool_from_env() -> ProviderPool:
    """Build a ProviderPool from environment-based Settings."""
    settings = get_settings()
    providers: List[DataProvider] = []

    if settings.tiingo_api_key:
        providers.append(TiingoProvider(ProviderConfig(
            name="tiingo",
            api_key=settings.tiingo_api_key,
            cps=settings.tiingo_cps,
            priority=0,
        )))

    if settings.yahoo_enabled:
        providers.append(YahooProvider(ProviderConfig(
            name="yahoo",
            cps=settings.yahoo_cps,
            priority=1,
        )))

    if settings.alphavantage_data_enabled and settings.alphavantage_key:
        providers.append(AlphaVantageProvider(ProviderConfig(
            name="alphavantage",
            api_key=settings.alphavantage_key,
            cps=settings.alphavantage_cps,
            priority=2,
        )))

    if not providers:
        raise ValueError(
            "No data providers configured. Set TIINGO_API_KEY, "
            "YAHOO_ENABLED=true, or ALPHAVANTAGE_KEY + ALPHAVANTAGE_DATA_ENABLED=true."
        )

    logging.info("Provider pool: %s (total %d CPS)",
                 ", ".join(f"{p.name}@{p.config.cps}cps" for p in providers),
                 sum(p.config.cps for p in providers))

    return ProviderPool(providers, max_retries=settings.provider_max_retries)
