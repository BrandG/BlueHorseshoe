"""OANDA financing-rate fetcher with date-versioned local cache.

Per FTMO_RULES.md §5.2 the backtest uses OANDA's published financing rates
as a proxy for FTMO's swap charges. We fetch today's snapshot once per day,
cache to data/swap_rates_<date>.json, and apply uniformly across the 10y
historical simulation. This is an approximation; historical rates are not
available from the OANDA REST API.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Optional

from bh_ftmo.backtest.swap import SwapRates
from bh_ftmo.data.oanda_client import OandaClient

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CACHE_DIR = REPO_ROOT / "data"


def fetch_oanda_financing_rates(client: OandaClient) -> dict[str, SwapRates]:
    """Fetch today's per-instrument financing rates from OANDA."""

    instruments = client.list_instruments()
    rates_by_symbol: dict[str, SwapRates] = {}
    for symbol, payload in instruments.items():
        financing = payload.get("financing")
        if not isinstance(financing, dict):
            continue
        long_rate = financing.get("longRate")
        short_rate = financing.get("shortRate")
        if long_rate is None or short_rate is None:
            continue
        rates_by_symbol[symbol] = SwapRates(long_rate=float(long_rate), short_rate=float(short_rate))
    return rates_by_symbol


def cache_path(today: date, cache_dir: Path = DEFAULT_CACHE_DIR) -> Path:
    return cache_dir / f"swap_rates_{today.isoformat()}.json"


def _serialize_rates(rates_by_symbol: dict[str, SwapRates]) -> dict[str, dict[str, float]]:
    return {symbol: asdict(rates) for symbol, rates in sorted(rates_by_symbol.items())}


def _deserialize_rates(payload: dict[str, object]) -> dict[str, SwapRates]:
    rates_by_symbol: dict[str, SwapRates] = {}
    for symbol, value in payload.items():
        if not isinstance(value, dict):
            continue
        long_rate = value.get("long_rate")
        short_rate = value.get("short_rate")
        if long_rate is None or short_rate is None:
            continue
        rates_by_symbol[symbol] = SwapRates(long_rate=float(long_rate), short_rate=float(short_rate))
    return rates_by_symbol


def fetch_or_load_cached(
    client: Optional[OandaClient],
    today: date,
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    no_swap: bool = False,
) -> dict[str, SwapRates]:
    """Return cached financing rates for ``today``, fetching on cache miss."""

    if no_swap:
        return {}

    path = cache_path(today, cache_dir=cache_dir)
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"invalid swap-rates cache payload in {path}")
        return _deserialize_rates(payload)

    if client is None:
        raise ValueError("OANDA client is required when swap cache is missing and --no-swap is not set")

    rates_by_symbol = fetch_oanda_financing_rates(client)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_serialize_rates(rates_by_symbol), indent=2, sort_keys=True), encoding="utf-8")
    return rates_by_symbol
