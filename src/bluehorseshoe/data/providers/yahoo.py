"""Yahoo Finance data provider."""
import logging
from typing import Optional, Dict

import yfinance as yf
from ratelimit import limits, sleep_and_retry  # pylint: disable=import-error

from bluehorseshoe.data.providers.base import DataProvider, ProviderConfig


class YahooProvider(DataProvider):
    """Fetches adjusted OHLCV data from Yahoo Finance via yfinance."""

    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self._rate_limited_fetch = sleep_and_retry(
            limits(calls=1, period=1.0 / config.cps)(self._fetch_raw)
        )

    def _fetch_raw(self, symbol: str, recent: bool) -> Optional[Dict]:
        ticker = yf.Ticker(symbol)
        if recent:
            df = ticker.history(period="6mo")
        else:
            df = ticker.history(start="2000-01-01")

        if df is None or df.empty:
            logging.error("Yahoo: no data for %s", symbol)
            return None

        result = {'name': symbol, 'days': []}
        for idx, row in df.iterrows():
            day = {
                'date': idx.strftime('%Y-%m-%d'),
                'open': round(float(row['Open']), 4),
                'high': round(float(row['High']), 4),
                'low': round(float(row['Low']), 4),
                'close': round(float(row['Close']), 4),
                'volume': int(row['Volume']),
            }
            day['midpoint'] = round((day['open'] + day['close']) / 2, 4)
            result['days'].append(day)

        return result

    def fetch(self, symbol: str, recent: bool = False) -> Optional[Dict]:
        try:
            return self._rate_limited_fetch(symbol, recent)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logging.error("Yahoo fetch failed for %s: %s", symbol, e)
            return None

    def is_available(self) -> bool:
        return True  # No API key needed
