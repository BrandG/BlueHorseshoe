"""Base classes for data providers."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, List


@dataclass
class ProviderConfig:
    """Configuration for a data provider."""
    name: str
    api_key: str = ""
    cps: int = 2
    enabled: bool = True
    priority: int = 0     # Lower = higher priority for fallback
    timeout: int = 30


class DataProvider(ABC):
    """Abstract base class for historical data providers.

    All providers return data in the canonical format:
    {"name": symbol, "days": [{"date", "open", "high", "low", "close", "volume", "midpoint"}, ...]}
    """

    def __init__(self, config: ProviderConfig):
        self.config = config
        self.name = config.name

    @abstractmethod
    def fetch(self, symbol: str, recent: bool = False) -> Optional[Dict]:
        """Fetch OHLCV data for a symbol.

        Args:
            symbol: Stock ticker symbol
            recent: If True, fetch ~6 months; if False, fetch full history

        Returns:
            Dict with "name" and "days" keys, or None on failure.
        """

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider is configured and ready to use."""
