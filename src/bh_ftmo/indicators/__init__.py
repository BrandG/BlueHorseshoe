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
from bh_ftmo.indicators.candlestick import (
    body_size,
    is_bearish,
    is_bearish_engulfing,
    is_bullish,
    is_bullish_engulfing,
    is_doji,
    is_hammer,
    is_shooting_star,
    lower_shadow,
    total_range,
    upper_shadow,
)
from bh_ftmo.indicators.pivots import (
    daily_ohlc,
    pivots,
)
from bh_ftmo.indicators.strength import (
    MAJORS,
    currency_strength,
    rank_currency_strength,
)
from bh_ftmo.indicators.trend import (
    adx,
    donchian,
    ema,
    ichimoku,
    sma,
    supertrend,
)
from bh_ftmo.indicators.volatility import (
    atr,
    atr_percent,
    bollinger_bands,
    true_range,
)

__all__ = [
    "ohlc_mid",
    # momentum
    "rsi",
    "macd",
    "stochastic",
    "cci",
    "williams_r",
    # volatility
    "true_range",
    "atr",
    "atr_percent",
    "bollinger_bands",
    # trend
    "sma",
    "ema",
    "adx",
    "supertrend",
    "donchian",
    "ichimoku",
    # pivots
    "daily_ohlc",
    "pivots",
    # candlestick
    "body_size",
    "total_range",
    "upper_shadow",
    "lower_shadow",
    "is_bullish",
    "is_bearish",
    "is_doji",
    "is_hammer",
    "is_shooting_star",
    "is_bullish_engulfing",
    "is_bearish_engulfing",
    # multi-pair
    "MAJORS",
    "currency_strength",
    "rank_currency_strength",
]
