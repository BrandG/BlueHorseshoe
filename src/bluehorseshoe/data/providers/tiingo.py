"""Tiingo data provider."""
import logging
from typing import Optional, Dict

import pandas as pd
import requests
from ratelimit import limits, sleep_and_retry  # pylint: disable=import-error

from bluehorseshoe.data.providers.base import DataProvider, ProviderConfig


class TiingoProvider(DataProvider):
    """Fetches adjusted OHLCV data from the Tiingo REST API."""

    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        # Per-instance rate limiter so each provider gets independent limiting
        self._rate_limited_fetch = sleep_and_retry(
            limits(calls=1, period=1.0 / config.cps)(self._fetch_raw)
        )

    def _fetch_raw(self, symbol: str, recent: bool) -> Optional[Dict]:
        url = f"https://api.tiingo.com/tiingo/daily/{symbol}/prices"
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Token {self.config.api_key}'
        }
        params = {'resampleFreq': 'daily'}

        if recent:
            start = (pd.Timestamp.now() - pd.Timedelta(days=180)).strftime('%Y-%m-%d')
            params['startDate'] = start
        else:
            params['startDate'] = '2000-01-01'

        response = requests.get(url, headers=headers, params=params,
                                timeout=self.config.timeout)

        if response.status_code == 404:
            logging.error("Tiingo: ticker not found: %s", symbol)
            return None
        if response.status_code == 429:
            logging.error("Tiingo: rate limit hit for %s", symbol)
            return None
        response.raise_for_status()

        json_data = response.json()
        if not json_data:
            logging.error("Tiingo: empty response for %s", symbol)
            return None

        result = {'name': symbol, 'days': []}
        for record in json_data:
            adj_open = round(float(record.get('adjOpen', record.get('open', 0))), 4)
            adj_high = round(float(record.get('adjHigh', record.get('high', 0))), 4)
            adj_low = round(float(record.get('adjLow', record.get('low', 0))), 4)
            adj_close = round(float(record.get('adjClose', record.get('close', 0))), 4)
            volume = int(record.get('adjVolume', record.get('volume', 0)))
            date_str = str(record.get('date', ''))[:10]

            day = {
                'date': date_str,
                'open': adj_open,
                'high': adj_high,
                'low': adj_low,
                'close': adj_close,
                'volume': volume,
            }
            day['midpoint'] = round((adj_open + adj_close) / 2, 4)
            result['days'].append(day)

        return result

    def fetch(self, symbol: str, recent: bool = False) -> Optional[Dict]:
        try:
            return self._rate_limited_fetch(symbol, recent)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logging.error("Tiingo fetch failed for %s: %s", symbol, e)
            return None

    def is_available(self) -> bool:
        return bool(self.config.api_key)
