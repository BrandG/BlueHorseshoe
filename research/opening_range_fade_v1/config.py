"""Config for the opening-range fade study.

Intraday US-equity study (1-min bars), so it does NOT use the daily-bar R harness
in research/_lib (that is for swing/forex). Rigor here = OOS split + second-period
holdout + cost stress + per-quarter robustness. See STUDY_README.md.
"""
import os

STUDY_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(STUDY_DIR, "..", ".."))
DUCKDB_PATH = os.path.join(REPO_ROOT, "data", "ohlcv.duckdb")

# Cache dirs holding AlphaVantage JSON ({SYM}_{YYYY-MM}.json intraday, {SYM}_DAILY.json daily).
# Defaults to the study's gitignored .cache/; extra dirs can be added via env (colon-separated)
# so a prior pull can be reused without re-downloading.
CACHE_DIRS = [os.path.join(STUDY_DIR, ".cache")] + [
    d for d in os.environ.get("ORB_EXTRA_CACHE_DIRS", "").split(":") if d
]
PRIMARY_CACHE_DIR = CACHE_DIRS[0]

# --- baskets ---
SYMBOLS_PRIMARY = ["SPY","QQQ","AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AMD","AVGO","NFLX"]
SYMBOLS_INDEX   = ["IWM","DIA","MDY","VTI","IWB","XLF","XLK","XLE","XLV","XLY",
                   "XLI","XLP","XLU","XLB","XLRE","XLC"]
SYMBOLS_HOLDOUT = ["SPY","QQQ","IWM"]   # the names that survived; second-period check

# --- strategy parameters (locked from the train-set sweep; do NOT re-fit on validation data) ---
ATR_MULT   = 0.25     # opening range must be >= this * daily ATR_14 to trade
FIB_TP_NEG = 0.382    # long (red candle) target, as fraction of range above L_15
FIB_TP_POS = 0.618    # short (green candle) target level, as fraction of range above L_15
STOP_FRAC  = 0.191    # 1U stop distance beyond the extreme, as fraction of range
BOUNCE_B   = 0.20     # Variant B: arm the limit only after price lifts this * range off the extreme

COST_PER_SHARE = 0.02 # assumed round-trip cost (dollars/share) for 'net' figures
OOS_SPLIT  = "2026-05-28"  # train = dates >= this; out-of-sample = before. (Primary basket only.)

# session windows (US/Eastern; AlphaVantage intraday is already ET, regular hours)
OPEN_START, OPEN_END = "09:30:00", "09:44:00"   # the 15-min opening candle
SIM_START,  SIM_END  = "09:45:00", "11:00:00"   # tradeable window
