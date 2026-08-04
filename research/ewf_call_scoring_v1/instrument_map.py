"""EWF instrument string -> (source, symbol) mapping.

Sources: "duckdb" (US equity dailies) and "oanda" (fx/metals/commodity/index CFDs, H1).
Unmappable strings return None and land in the no-instrument-data funnel bucket with
their raw string preserved — the unmapped-string frequency table is part of the report
(auditability: a mapping gap must be distinguishable from a data gap).

Known permanent gaps (no price source held): crypto (BTC/ETH), USDX/DXY, IBEX and other
exchange indices OANDA lacks. These are REPORTED, not silently dropped.
"""
from __future__ import annotations

import re

CCY = {"USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF", "SGD", "ZAR",
       "NOK", "SEK", "PLN", "HUF", "CZK", "TRY", "MXN", "DKK", "HKD", "CNH", "INR"}

# canonicalized alias -> OANDA instrument
OANDA_ALIASES = {
    # metals
    "XAUUSD": "XAU_USD", "GOLD": "XAU_USD", "GC": "XAU_USD", "GCF": "XAU_USD",
    "XAGUSD": "XAG_USD", "SILVER": "XAG_USD", "SI": "XAG_USD", "SIF": "XAG_USD",
    "COPPER": "XCU_USD", "HG": "XCU_USD", "HGF": "XCU_USD", "XCUUSD": "XCU_USD",
    "PALLADIUM": "XPD_USD", "PA": "XPD_USD", "PAF": "XPD_USD", "XPDUSD": "XPD_USD",
    "PLATINUM": "XPT_USD", "PL": "XPT_USD", "PLF": "XPT_USD", "XPTUSD": "XPT_USD",
    # energy / ags
    "NG": "NATGAS_USD", "NGF": "NATGAS_USD", "NATGAS": "NATGAS_USD", "NATURALGAS": "NATGAS_USD",
    "CL": "WTICO_USD", "CLF": "WTICO_USD", "OIL": "WTICO_USD", "WTI": "WTICO_USD",
    "USOIL": "WTICO_USD", "CRUDEOIL": "WTICO_USD",
    "BRENT": "BCO_USD", "UKOIL": "BCO_USD", "BCO": "BCO_USD",
    "ZW": "WHEAT_USD", "ZWF": "WHEAT_USD", "WHEAT": "WHEAT_USD",
    "ZC": "CORN_USD", "ZCF": "CORN_USD", "CORN": "CORN_USD",
    "ZS": "SOYBN_USD", "ZSF": "SOYBN_USD", "SOYBEAN": "SOYBN_USD", "SOYBEANS": "SOYBN_USD",
    "SUGAR": "SUGAR_USD", "SB": "SUGAR_USD",
    # index CFDs (availability re-checked against the live account at fetch time)
    "SPX": "SPX500_USD", "SPX500": "SPX500_USD", "SP500": "SPX500_USD",
    "ES": "SPX500_USD", "ESF": "SPX500_USD",
    "NDX": "NAS100_USD", "NAS100": "NAS100_USD", "NASDAQ": "NAS100_USD",
    "NQ": "NAS100_USD", "NQF": "NAS100_USD", "NASDAQ100": "NAS100_USD",
    "DOW": "US30_USD", "DOWJONES": "US30_USD", "DJIA": "US30_USD", "US30": "US30_USD",
    "YM": "US30_USD", "YMF": "US30_USD",
    "NIKKEI": "JP225_USD", "NKD": "JP225_USD", "NKDF": "JP225_USD",
    "N225": "JP225_USD", "JP225": "JP225_USD", "NI225": "JP225_USD", "NKI": "JP225_USD",
    "DAX": "DE30_EUR", "GER30": "DE30_EUR", "GER40": "DE30_EUR", "DE30": "DE30_EUR", "DE40": "DE30_EUR",
    "FTSE": "UK100_GBP", "UK100": "UK100_GBP", "FTSE100": "UK100_GBP",
    "CAC": "FR40_EUR", "CAC40": "FR40_EUR",
    "NIFTY": "IN50_USD", "NIFTY50": "IN50_USD",
    "ASX": "AU200_AUD", "ASX200": "AU200_AUD",
    "HSI": "HK33_HKD", "HANGSENG": "HK33_HKD", "HANGSENGINDEX": "HK33_HKD",
    "IBEX": "ESPIX_EUR", "IBEX35": "ESPIX_EUR", "ESPIX": "ESPIX_EUR",
    "STOXX": "EU50_EUR", "STOXX50": "EU50_EUR", "EUSTOXX": "EU50_EUR", "EU50": "EU50_EUR",
    "SMI": "CH20_CHF", "AEX": "NL25_EUR",
    "RUSSELL": "US2000_USD", "RUSSELL2000": "US2000_USD", "RUT": "US2000_USD",
    "RTY": "US2000_USD", "RTYF": "US2000_USD", "US2000": "US2000_USD",
    "KOSPI": "KR200_KRW", "CHINAA50": "CN50_USD", "CN50": "CN50_USD",
    # crypto (OANDA CFDs; EWF covers BTC/ETH heavily)
    "BTCUSD": "BTC_USD", "BTC": "BTC_USD", "BITCOIN": "BTC_USD",
    "ETHUSD": "ETH_USD", "ETH": "ETH_USD", "ETHEREUM": "ETH_USD",
    "LTCUSD": "LTC_USD", "LTC": "LTC_USD", "LITECOIN": "LTC_USD",
    "BCHUSD": "BCH_USD", "BCH": "BCH_USD",
}

# Instruments EWF discusses that we deliberately DO NOT map, with the reason.
# Reported in the funnel as no-instrument-data so the gap stays visible.
#
# TNX/TYX/FVX are Treasury YIELD indices. OANDA's USB10Y_USD etc. are bond PRICE
# CFDs, which move INVERSELY and are quoted on a completely different scale — a
# post's "target 4.5%" is meaningless against a ~110 bond price. Mapping these
# would silently invert the direction of every rates call. Left unmapped on purpose.
#
# USDX/DXY: dollar index; OANDA offers no DXY contract and a synthetic basket would
# not reproduce the post's stated levels.
UNMAPPABLE_REASONS = {
    "TNX": "yield index, not a price series (would invert vs bond CFDs)",
    "TYX": "yield index, not a price series",
    "FVX": "yield index, not a price series",
    "USDX": "dollar index — no OANDA contract",
    "DXY": "dollar index — no OANDA contract",
    "IBC-MAC": "unidentified ticker",
    "TASI": "Saudi index — no source held",
    "TRAN": "Dow Transports — no source held",
}


# Index/futures names that collide with real US tickers — must never fall through
# to the equity mapper (EWF's "IBEX" is the Spanish index, not Ibex Ltd; "USDX" is
# the dollar index, not the ETF). "DOW"/"GOLD" collide too but the OANDA aliases
# above intercept them first (EWF usage is overwhelmingly the index/metal).
EQUITY_DENY = {"USDX", "DXY", "IBEX", "TNX", "TYX", "FVX", "TASI", "NI225", "NKI",
               "RTY", "RUT", "TRAN", "SMI", "AEX", "BTC", "ETH", "LTC", "BCH"}


def _canon(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", s.upper().replace("#F", "F"))


def map_instrument(raw: str | None, equity_symbols: set[str]) -> tuple[str, str] | None:
    """Map an extracted instrument string to (source, symbol), or None."""
    if not raw or not isinstance(raw, str):
        return None
    c = _canon(raw)
    if not c:
        return None
    if c in OANDA_ALIASES:
        return ("oanda", OANDA_ALIASES[c])
    # fx pair: 6 letters splitting into two known currency codes (EURUSD, EUR/USD, ...)
    if len(c) == 6 and c[:3] in CCY and c[3:] in CCY:
        return ("oanda", f"{c[:3]}_{c[3:]}")
    if "_" in raw:
        a, b = raw.upper().split("_", 1)
        if a in CCY and b in CCY:
            return ("oanda", f"{a}_{b}")
    # US equity/ETF ticker held in DuckDB (strip a leading $)
    tick = raw.upper().lstrip("$").strip()
    if tick in EQUITY_DENY or c in EQUITY_DENY:
        return None
    if tick in equity_symbols:
        return ("duckdb", tick)
    return None
