"""
Dependency injection container for BlueHorseshoe application.
Manages application-scoped resources like MongoDB connections and configuration.
"""
import logging
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING
from pymongo import MongoClient
from pymongo.database import Database
from .config import Settings, get_settings
from .invalid_symbols import load_invalid_symbols, resolve_invalid_symbols_path

if TYPE_CHECKING:
    from bluehorseshoe.data.ibkr_client import IBKRClient
    from bluehorseshoe.data.duckdb_store import DuckDBStore

logger = logging.getLogger(__name__)

@dataclass
class AppContainer:
    """
    Application-level dependency container.
    Manages lifecycle of app-scoped resources (MongoDB client, configuration, etc.).
    """
    settings: Settings
    _mongo_client: Optional[MongoClient] = field(default=None, init=False)
    _invalid_symbols: Optional[list] = field(default=None, init=False)
    _ibkr_client: Optional["IBKRClient"] = field(default=None, init=False)
    _duckdb_store: Optional["DuckDBStore"] = field(default=None, init=False)

    def get_mongo_client(self) -> MongoClient:
        """
        Get or create MongoDB client (lazy initialization).
        The client is reused across requests for connection pooling.
        """
        if self._mongo_client is None:
            try:
                self._mongo_client = MongoClient(
                    self.settings.mongo_uri,
                    serverSelectionTimeoutMS=5000,
                    connectTimeoutMS=5000
                )
                # Test connection
                self._mongo_client.server_info()
                logger.info("MongoDB client initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize MongoDB client: {e}")
                raise
        return self._mongo_client

    def get_database(self) -> Database:
        """
        Get MongoDB database instance.
        Returns the database object for the configured database name.
        """
        return self.get_mongo_client()[self.settings.mongo_db]

    def get_ibkr_client(self) -> "IBKRClient":
        """
        Get or create IBKRClient (lazy initialization).
        """
        if self._ibkr_client is None:
            from bluehorseshoe.data.ibkr_client import IBKRClient, IBKRConfig  # pylint: disable=import-outside-toplevel
            config = IBKRConfig(
                host=self.settings.ibkr_host,
                port=self.settings.ibkr_port,
                client_id=self.settings.ibkr_client_id,
                read_only=not self.settings.paper_trading_enabled,
            )
            self._ibkr_client = IBKRClient(config=config)
        return self._ibkr_client

    def get_historical_store(self) -> "DuckDBStore":
        """
        Get or create DuckDBStore for OHLCV data (lazy initialization).
        """
        if self._duckdb_store is None:
            from bluehorseshoe.data.duckdb_store import DuckDBStore  # pylint: disable=import-outside-toplevel
            self._duckdb_store = DuckDBStore(self.settings.duckdb_path)
            logger.info("DuckDB store initialized at %s", self.settings.duckdb_path)
        return self._duckdb_store

    def get_invalid_symbols(self) -> list:
        """
        Load and cache the list of invalid symbols.
        These symbols are excluded from processing.
        """
        if self._invalid_symbols is None:
            invalid_symbols_path = resolve_invalid_symbols_path(self.settings.base_path)
            self._invalid_symbols = load_invalid_symbols(invalid_symbols_path)
            if self._invalid_symbols:
                logger.info(f"Loaded {len(self._invalid_symbols)} invalid symbols")
            else:
                logger.warning(f"Invalid symbols file not found at {invalid_symbols_path}")
        return self._invalid_symbols

    def close(self):
        """
        Close and cleanup all resources.
        Should be called during application shutdown.
        """
        if self._ibkr_client is not None:
            try:
                self._ibkr_client.close()
                logger.info("IBKR client closed successfully")
            except Exception as e:
                logger.error(f"Error closing IBKR client: {e}")
            finally:
                self._ibkr_client = None

        if self._duckdb_store is not None:
            try:
                self._duckdb_store.close()
                logger.info("DuckDB store closed successfully")
            except Exception as e:
                logger.error(f"Error closing DuckDB store: {e}")
            finally:
                self._duckdb_store = None

        if self._mongo_client is not None:
            try:
                self._mongo_client.close()
                logger.info("MongoDB client closed successfully")
            except Exception as e:
                logger.error(f"Error closing MongoDB client: {e}")
            finally:
                self._mongo_client = None

def create_app_container(settings: Optional[Settings] = None) -> AppContainer:
    """
    Factory function for creating an AppContainer instance.

    Args:
        settings: Optional Settings instance. If not provided, will load from environment.

    Returns:
        AppContainer instance with the specified or default settings.
    """
    if settings is None:
        settings = get_settings()
    return AppContainer(settings=settings)
