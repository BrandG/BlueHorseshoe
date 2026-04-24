"""BH FTMO technical indicators — fully independent of bluehorseshoe/ per decision 15D.

No code is shared with the equity indicators. A bug in here cannot affect the
equity pipeline, and vice versa. Classic daily-bar default parameters are used;
Phase 2c will tune lookbacks for 4h forex bars empirically via backtest.

Usage:

    from bh_ftmo.data.fx_store import FxStore
    from bh_ftmo.indicators import ohlc_mid, rsi, macd

    store = FxStore(read_only=True)
    df = store.load("EUR_USD", granularity="H4")
    ohlc = ohlc_mid(df)
    rsi14 = rsi(ohlc, period=14)
    macd_df = macd(ohlc)
"""

from bh_ftmo.indicators._common import ohlc_mid
from bh_ftmo.indicators.momentum import (
    cci,
    macd,
    rsi,
    stochastic,
    williams_r,
)

__all__ = [
    "ohlc_mid",
    "rsi",
    "macd",
    "stochastic",
    "cci",
    "williams_r",
]
