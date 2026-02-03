"""
Strategy constants for BlueHorseshoe.
"""

TREND_PERIOD = 20
STRONG_R2_THRESHOLD = 0.7
WEAK_R2_THRESHOLD = 0.3
MIN_VOLUME_THRESHOLD = 100000
MIN_STOCK_PRICE = 5.0
MAX_STOCK_PRICE = 500.0
STOP_LOSS_FACTOR = 0.97
TAKE_PROFIT_FACTOR = 1.05

EMA_MARGIN_MULTIPLIER = 1.0
VOLUME_MULTIPLIER = 1.0

# Technical Scoring Constants
OVERSOLD_RSI_THRESHOLD_EXTREME = 30
OVERSOLD_RSI_REWARD_EXTREME = -5.0
OVERSOLD_RSI_THRESHOLD_MODERATE = 35
OVERSOLD_RSI_REWARD_MODERATE = -2.0
OVERSOLD_BB_REWARD = -3.0
OVERSOLD_BB_POSITION_THRESHOLD = 0.1

# Mean Reversion Specific (Always positive bonuses)
MR_OVERSOLD_RSI_REWARD_EXTREME = 6.0
MR_OVERSOLD_RSI_REWARD_MODERATE = 3.0
MR_OVERSOLD_BB_REWARD = 4.0
MR_BELLOW_LOW_BB_BONUS = 2.0  # Extra bonus if price is actually below BB Lower
MR_CONFLUENCE_BONUS = 3.0 # Bonus for both RSI and BB oversold

PENALTY_EMA_OVEREXTENSION_MODERATE = -3.0
PENALTY_EMA_OVEREXTENSION_EXTREME = -7.0
PENALTY_EMA_THRESHOLD_MODERATE = 0.07
PENALTY_EMA_THRESHOLD_EXTREME = 0.12

PENALTY_RSI_THRESHOLD_EXTREME = 75
PENALTY_RSI_SCORE_EXTREME = -5.0
PENALTY_RSI_THRESHOLD_MODERATE = 70
PENALTY_RSI_SCORE_MODERATE = -2.0
PENALTY_VOLUME_EXHAUSTION = -3.0

# ATR Timing Optimization Constants
ATR_WINDOW = 14
ATR_MULTIPLIER_UPTREND = 0.5
ATR_MULTIPLIER_DOWNTREND = 1.0

# Reward-to-Risk Filtering
MIN_RR_RATIO_BASELINE = 1.0
MIN_RR_RATIO_MEAN_REVERSION = 0.8
MAX_RISK_PERCENT = 0.10

# Volume Confirmation
MIN_REL_VOLUME = 0.8  # Must be at least average volume

# Multi-Timeframe Alignment
REQUIRE_WEEKLY_UPTREND = False

# ============================================
# Dynamic Entry Strategy Configuration
# ============================================

# Signal Strength Classification Thresholds
# Data-driven thresholds based on actual score distribution (Feb 2026)
# These represent: EXTREME (top 1%), HIGH (top 5%), MEDIUM (top 20%), LOW (top 40%)
SIGNAL_STRENGTH_THRESHOLDS = {
    'EXTREME': 20,    # Score >= 20 (top 1% of signals)
    'HIGH': 14.5,     # Score >= 14.5 (top 5% of signals)
    'MEDIUM': 7,      # Score >= 7 (top 20% of signals)
    'LOW': 2          # Score >= 2 (top 40% of signals)
    # WEAK: Score < 2 (bottom 60% of signals)
}

# Entry Discount by Signal Strength (ATR multipliers)
ENTRY_DISCOUNT_BY_SIGNAL = {
    'EXTREME': 0.05,   # At near-market for best setups
    'HIGH': 0.10,      # Slight discount
    'MEDIUM': 0.20,    # Current default
    'LOW': 0.35,       # Conservative
    'WEAK': 0.50       # Very conservative
}

# Feature flag to enable/disable dynamic entry
ENABLE_DYNAMIC_ENTRY = True  # Set to False to revert to 0.2 ATR default
