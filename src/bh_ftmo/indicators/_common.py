"""Shared helpers for BH FTMO indicators."""
from __future__ import annotations

import pandas as pd

OHLC_COLUMNS = ("open", "high", "low", "close")


def ohlc_mid(df: pd.DataFrame) -> pd.DataFrame:
    """Convert an FxStore bid+ask OHLC DataFrame into a 4-column mid-price DataFrame.

    Expects ``open_bid``, ``open_ask``, ``high_bid``, ``high_ask``, ``low_bid``,
    ``low_ask``, ``close_bid``, ``close_ask``. Returns a DataFrame with columns
    ``open``, ``high``, ``low``, ``close`` indexed identically to ``df``.

    Mid prices are the arithmetic mean of bid + ask. For spread-aware logic
    (entry cost, stop-loss fills, etc.), callers use the bid/ask columns
    directly — this helper is for indicators that only care about "price".
    """
    return pd.DataFrame(
        {
            "open": (df["open_bid"] + df["open_ask"]) / 2,
            "high": (df["high_bid"] + df["high_ask"]) / 2,
            "low": (df["low_bid"] + df["low_ask"]) / 2,
            "close": (df["close_bid"] + df["close_ask"]) / 2,
        },
        index=df.index,
    )


def _require_ohlc(ohlc: pd.DataFrame) -> None:
    missing = [c for c in OHLC_COLUMNS if c not in ohlc.columns]
    if missing:
        raise ValueError(f"ohlc DataFrame missing columns: {missing}")
