"""Alpha Vantage data provider."""
import logging
from typing import Optional, Dict

import requests
from ratelimit import limits, sleep_and_retry  # pylint: disable=import-error

from bluehorseshoe.data.providers.base import DataProvider, ProviderConfig


class AlphaVantageProvider(DataProvider):
    """Fetches adjusted OHLCV data from the Alpha Vantage REST API."""

    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self._rate_limited_fetch = sleep_and_retry(
            limits(calls=1, period=1.0 / config.cps)(self._fetch_raw)
        )

    def _fetch_raw(self, symbol: str, recent: bool) -> Optional[Dict]:
        outputsize = "compact" if recent else "full"
        url = "https://www.alphavantage.co/query"
        params = {
            "function": "TIME_SERIES_DAILY_ADJUSTED",
            "symbol": symbol,
            "outputsize": outputsize,
            "apikey": self.config.api_key,
        }

        response = requests.get(url, params=params, timeout=self.config.timeout)
        response.raise_for_status()
        data = response.json()

        ts_key = "Time Series (Daily)"
        if ts_key not in data:
            logging.error("AlphaVantage: no time series for %s (keys: %s)",
                          symbol, list(data.keys()))
            return None

        result = {'name': symbol, 'days': []}
        for date_str, values in data[ts_key].items():
            day = {
                'date': date_str,
                'open': round(float(values['1. open']), 4),
                'high': round(float(values['2. high']), 4),
                'low': round(float(values['3. low']), 4),
                'close': round(float(values['5. adjusted close']), 4),
                'volume': int(values['6. volume']),
            }
            day['midpoint'] = round((day['open'] + day['close']) / 2, 4)
            result['days'].append(day)

        # AV returns newest-first; sort to oldest-first like Tiingo/Yahoo
        result['days'].sort(key=lambda d: d['date'])
        return result

    def fetch(self, symbol: str, recent: bool = False) -> Optional[Dict]:
        try:
            return self._rate_limited_fetch(symbol, recent)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logging.error("AlphaVantage fetch failed for %s: %s", symbol, e)
            return None

    def is_available(self) -> bool:
        return bool(self.config.api_key)
