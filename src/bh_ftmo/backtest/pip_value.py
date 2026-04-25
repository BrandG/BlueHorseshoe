"""FX pip-value mechanics for account-currency-aware position sizing.

The backtest sizes risk in account currency, so pip value must convert from the
pair's quote currency into the account currency at the current spot rate. The
helper in this module resolves that conversion path from available market rates
without relying on engine-global state.
"""

from __future__ import annotations

# pylint: disable=too-many-locals,redefined-outer-name

from collections import deque
import json
from pathlib import Path

from bh_ftmo.backtest.types import PairSpec

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = REPO_ROOT / "src" / "bh_ftmo_config.json"


def _canonical_symbol(symbol: str) -> str:
    """Normalize known pair symbol variants to ``BASE_QUOTE`` form."""

    raw = symbol.strip().upper()
    if raw.endswith(".SIM"):
        raw = raw[:-4]
    if raw.endswith("=X"):
        raw = raw[:-2]
    raw = raw.replace("/", "_")
    if "_" in raw:
        base, quote = raw.split("_", 1)
        return f"{base}_{quote}"
    if len(raw) != 6:
        raise ValueError(f"unsupported pair symbol: {symbol}")
    return f"{raw[:3]}_{raw[3:]}"


def _split_pair(symbol: str) -> tuple[str, str]:
    """Return ``(base, quote)`` for a supported FX pair symbol string."""

    canonical = _canonical_symbol(symbol)
    base, quote = canonical.split("_", 1)
    return base, quote


def _load_supported_symbols() -> frozenset[str]:
    """Return the configured instrument universe as canonical pair symbols."""

    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return frozenset(_canonical_symbol(item["ftmo"]) for item in payload.get("instruments", []))


SUPPORTED_SYMBOLS = _load_supported_symbols()


def pip_value_in_account_ccy(
    pair: PairSpec,
    account_ccy: str,
    quote_to_account_rate: float,
) -> float:
    """Return pip value per lot in account currency.

    ``quote_to_account_rate`` is the conversion rate from one unit of the pair's
    quote currency into ``account_ccy``. For example, for ``USD_JPY`` in a USD
    account the quote currency is JPY, so the conversion is JPY→USD
    (approximately ``1 / USDJPY``). FTMO's published examples only reconcile if
    this conversion rate is multiplied, not divided, into the raw pip amount.
    """

    del account_ccy
    if quote_to_account_rate <= 0:
        raise ValueError("quote_to_account_rate must be positive")
    return pair.pip_size * pair.contract_size * quote_to_account_rate


def quote_to_account_rate(
    pair_symbol: str,
    account_ccy: str,
    rates_at_ts: dict[str, float],
) -> float:
    """Resolve the QUOTE→account conversion rate from current spot prices.

    The input prices are mid rates keyed by pair symbol. Each price is treated
    as ``BASE/QUOTE``. The resolver builds a simple currency graph and walks from
    the pair's quote currency to the requested account currency.
    """

    canonical_pair = _canonical_symbol(pair_symbol)
    if canonical_pair not in SUPPORTED_SYMBOLS:
        raise ValueError(f"unsupported pair symbol: {pair_symbol}")

    _, quote_ccy = _split_pair(canonical_pair)
    account_ccy = account_ccy.upper()
    if quote_ccy == account_ccy:
        return 1.0

    graph: dict[str, list[tuple[str, float]]] = {}
    for symbol, rate in rates_at_ts.items():
        if rate <= 0:
            raise ValueError(f"spot rate must be positive: {symbol}={rate}")
        base_ccy, quote = _split_pair(symbol)
        graph.setdefault(base_ccy, []).append((quote, rate))
        graph.setdefault(quote, []).append((base_ccy, 1.0 / rate))

    queue: deque[tuple[str, float]] = deque([(quote_ccy, 1.0)])
    visited = {quote_ccy}
    while queue:
        currency, path_rate = queue.popleft()
        if currency == account_ccy:
            return path_rate
        for neighbor, edge_rate in graph.get(currency, []):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            queue.append((neighbor, path_rate * edge_rate))

    raise ValueError(f"no quote-to-account conversion path for {pair_symbol} into {account_ccy}")
