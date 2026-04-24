"""Currency strength meter — the first multi-pair indicator for BH FTMO.

For each currency C and timestamp T, strength[C, T] is the average log-return
contribution of C across every pair it appears in over a lookback window.

Intuition: EUR is "strong" when EUR/USD, EUR/GBP, EUR/JPY etc. are all rising.
If only EUR/USD is rising but EUR/AUD is flat, EUR is only weakly strong —
the move is USD-driven. The meter disentangles which leg is driving.

Formula
-------
For each pair P (base/quote) over lookback N bars:
    r_P = log(close[T]) - log(close[T - N])

Contribution to each currency:
    base:  +r_P
    quote: -r_P

For each currency C:
    strength[C, T] = mean over P of contribution (skipping NaN)

Rank transformation (optional, via :func:`rank_currency_strength`) converts
raw strengths to ordinal ranks (1 = weakest, N = strongest) at each timestamp
— useful for "trade the strong against the weak" logic.

Defaults: ``lookback=14`` (matching RSI for intuition), ``currencies``
covers the 8 majors. Phase 2c tunes lookback empirically.
"""
from __future__ import annotations

from typing import Iterable, Optional, Sequence

import numpy as np
import pandas as pd

MAJORS: tuple[str, ...] = ("USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF")


def _split_pair(symbol: str) -> Optional[tuple[str, str]]:
    """Return (base, quote) from a 'BASE_QUOTE' OANDA symbol, or None."""
    parts = symbol.split("_")
    if len(parts) != 2:
        return None
    base, quote = parts
    if len(base) != 3 or len(quote) != 3:
        return None
    return base.upper(), quote.upper()


def _close_series(df: pd.DataFrame) -> pd.Series:
    """Return the 'close' series from either a mid-OHLC or bid/ask DataFrame."""
    if "close" in df.columns:
        return df["close"]
    if "close_bid" in df.columns and "close_ask" in df.columns:
        return (df["close_bid"] + df["close_ask"]) / 2.0
    raise ValueError("DataFrame must contain 'close' or 'close_bid'+'close_ask'")


def currency_strength(
    pairs: dict[str, pd.DataFrame],
    *,
    lookback: int = 14,
    currencies: Sequence[str] = MAJORS,
) -> pd.DataFrame:
    """Compute per-currency strength across the supplied pair DataFrames.

    Parameters
    ----------
    pairs:
        Mapping ``{symbol: DataFrame}`` where symbols follow OANDA convention
        (``BASE_QUOTE``, e.g. ``"EUR_USD"``) and each DataFrame has either a
        ``close`` column or ``close_bid`` + ``close_ask``.
    lookback:
        Number of bars over which to compute log-return contribution.
    currencies:
        Currencies to score. Each must appear in at least one pair, else its
        column will be all-NaN.

    Returns
    -------
    pd.DataFrame
        Indexed by the union of input timestamps, one column per currency,
        values are averaged log-return contributions over ``lookback`` bars.
    """
    if lookback < 1:
        raise ValueError(f"lookback must be >= 1, got {lookback}")
    if not pairs:
        raise ValueError("pairs is empty")

    # Classify each pair and compute its log-return series.
    pair_returns: dict[str, pd.Series] = {}
    for sym, df in pairs.items():
        parts = _split_pair(sym)
        if parts is None:
            continue
        close = _close_series(df)
        # log-return over lookback
        r = np.log(close).diff(lookback)
        pair_returns[sym] = r

    # Union index across pair returns
    union_index: Optional[pd.Index] = None
    for r in pair_returns.values():
        union_index = r.index if union_index is None else union_index.union(r.index)
    if union_index is None:
        raise ValueError("no valid currency pairs in input")

    out: dict[str, pd.Series] = {}
    for ccy in currencies:
        ccy_u = ccy.upper()
        contributions: list[pd.Series] = []
        for sym, r in pair_returns.items():
            base, quote = _split_pair(sym)  # type: ignore[misc]
            aligned = r.reindex(union_index)
            if base == ccy_u:
                contributions.append(aligned)
            elif quote == ccy_u:
                contributions.append(-aligned)
        if contributions:
            # Mean across contributing pairs per timestamp (skipna=True default)
            out[ccy_u] = pd.concat(contributions, axis=1).mean(axis=1)
        else:
            out[ccy_u] = pd.Series(np.nan, index=union_index, name=ccy_u)

    result = pd.DataFrame(out, index=union_index)
    result.columns = [c.upper() for c in currencies]
    return result


def rank_currency_strength(strength: pd.DataFrame) -> pd.DataFrame:
    """Convert raw strengths to ordinal ranks per row.

    1 = weakest of the row, N = strongest. Ties get averaged ranks (pandas
    default). Rows where every value is NaN come back as NaN.
    """
    return strength.rank(axis=1, method="average", na_option="keep")
