"""Synthesized DXY index + per-pair rolling correlation with it.

Per the Phase 0.5 OANDA probe finding: OANDA doesn't expose the DXY index
directly on Brand's account. We synthesize it from the six constituent pairs
using the standard ICE formula. This is actually better than a raw feed
because it aligns perfectly to our 4h bar grid.

DXY formula (ICE definition):
    DXY = 50.14348112 × EURUSD^-0.576 × USDJPY^+0.136 × GBPUSD^-0.119
                     × USDCAD^+0.091 × USDSEK^+0.042 × USDCHF^+0.036

Sign convention: negative exponent when USD is the QUOTE (the pair moves
inversely to USD); positive when USD is the BASE. Weights correspond to
basket shares of the six constituent economies.

Use cases
---------
- Per-pair correlation with DXY: "is this move USD-driven or counter-
  currency-driven?" USD-base pairs (USD_JPY) should show high positive
  correlation with DXY; USD-quote pairs (EUR_USD) should show high
  negative correlation.
- Regime filter: "only take long USD trades when the pair's 20-bar
  correlation with DXY is > 0.7 and DXY itself is trending up."
"""
from __future__ import annotations

from typing import Iterable, Optional

import numpy as np
import pandas as pd

from bh_ftmo.indicators.strength import _close_series, _split_pair

# ICE DXY weights. Sign encodes USD position:
#   negative ⇒ USD is the QUOTE (pair inversely reflects USD strength)
#   positive ⇒ USD is the BASE  (pair directly reflects USD strength)
DXY_WEIGHTS: dict[str, float] = {
    "EUR_USD": -0.576,
    "USD_JPY": +0.136,
    "GBP_USD": -0.119,
    "USD_CAD": +0.091,
    "USD_SEK": +0.042,
    "USD_CHF": +0.036,
}

DXY_BASE_CONSTANT: float = 50.14348112


def synthesize_dxy(
    pairs: dict[str, pd.DataFrame],
    *,
    weights: dict[str, float] = DXY_WEIGHTS,
    base_constant: float = DXY_BASE_CONSTANT,
) -> pd.Series:
    """Synthesize the DXY index from the six constituent pairs.

    Every pair in ``weights`` must be present in ``pairs``. Each pair's
    DataFrame must have a ``close`` column or both ``close_bid`` and
    ``close_ask``. Output is a tz-naive-indexed :class:`Series` whose index
    is the **intersection** of the constituent closes (so every row has
    all 6 prices).
    """
    missing = [sym for sym in weights if sym not in pairs]
    if missing:
        raise ValueError(f"synthesize_dxy missing constituent pairs: {missing}")

    closes: dict[str, pd.Series] = {sym: _close_series(pairs[sym]) for sym in weights}

    # Align on the intersection of indices so every row has a price for every pair
    frame = pd.DataFrame(closes).dropna(how="any")

    log_sum = pd.Series(0.0, index=frame.index)
    for sym, w in weights.items():
        log_sum = log_sum + w * np.log(frame[sym])
    dxy = base_constant * np.exp(log_sum)
    dxy.name = "dxy"
    return dxy


def dxy_correlation(
    pair_close: pd.Series,
    dxy: pd.Series,
    *,
    window: int = 20,
) -> pd.Series:
    """Rolling correlation between a pair's log-returns and DXY's log-returns.

    Returned values in [-1, 1]. The first ``window`` rows are NaN.

    Sign interpretation:
      - Close to +1: pair moves WITH DXY (USD-base pair, USD dominant)
      - Close to -1: pair moves AGAINST DXY (USD-quote pair, USD dominant)
      - Near 0: move is driven by the non-USD side, not USD

    Sign does NOT by itself tell you the trend direction — it tells you
    the source of the move.
    """
    if window < 2:
        raise ValueError(f"window must be >= 2 for correlation, got {window}")
    pair_ret = np.log(pair_close).diff()
    dxy_ret = np.log(dxy).diff()
    pair_ret, dxy_ret = pair_ret.align(dxy_ret, join="inner")
    out = pair_ret.rolling(window, min_periods=window).corr(dxy_ret)
    out.name = f"dxy_corr_{window}"
    return out


def usd_pair_correlations(
    pairs: dict[str, pd.DataFrame],
    dxy: pd.Series,
    *,
    window: int = 20,
    symbols: Optional[Iterable[str]] = None,
) -> pd.DataFrame:
    """Rolling DXY correlation for every USD-involving pair in ``pairs``.

    If ``symbols`` is provided, restrict to that subset (still must be in
    ``pairs``). Output columns are symbols; rows share DXY's index.
    """
    out: dict[str, pd.Series] = {}
    iterable = symbols if symbols is not None else list(pairs.keys())
    for sym in iterable:
        parts = _split_pair(sym)
        if parts is None:
            continue
        base, quote = parts
        if base != "USD" and quote != "USD":
            continue
        if sym not in pairs:
            continue
        close = _close_series(pairs[sym])
        out[sym] = dxy_correlation(close, dxy, window=window)
    if not out:
        return pd.DataFrame(index=dxy.index)
    df = pd.DataFrame(out)
    df = df.reindex(dxy.index)
    return df
