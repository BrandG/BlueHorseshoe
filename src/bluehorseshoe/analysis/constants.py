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
MIN_RR_RATIO_BASELINE = 0.5
MIN_RR_RATIO_MEAN_REVERSION = 0.5
MAX_RISK_PERCENT = 0.05

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

# Market Cap Universe Filter
MIN_MARKET_CAP = 300_000_000  # $300M — approximate Russell 3000 floor

# ---------------------------------------------------------------------------
# Deep-Oversold strategy (validated 2026-06-04 — research/indicator_screen/)
# The one entry edge to clear the honest gauntlet (de-overlap → era → crash →
# cost/liquidity). The signal is PERSISTENCE, not the RSI<30 crossing: forward
# bracket return rises monotonically with how long RSI has stayed below 30
# (onset≈0 → age6+ = +0.44R nonbull). Mechanical & ML-free by design — the
# validated backtest used none of the MR scorer's ML/context/motif machinery.
# Survives realistic frictions at +0.142R/trade (t6.2), STRONGEST in liquid
# names, so a hard $-volume floor is part of the edge, not just hygiene.
# ---------------------------------------------------------------------------
DEEP_OVERSOLD_RSI_THRESHOLD = 30.0       # RSI(14) below this = "oversold"
DEEP_OVERSOLD_MIN_AGE = 3                # require >= this many consecutive oversold bars
DEEP_OVERSOLD_MIN_DOLLAR_VOLUME = 25_000_000.0   # 20d avg $-volume floor (>$25M tier: +0.139R t4.6)
DEEP_OVERSOLD_STOP_MULT = 1.0            # SL = 1*ATR below entry  (the validated 2:1 bracket)
DEEP_OVERSOLD_TARGET_MULT = 2.0          # TP = 2*ATR above entry
DEEP_OVERSOLD_MIN_RR = 1.5               # 2:1 geometry clears this; guards against degenerate ATR
DEEP_OVERSOLD_PRIOR_WINRATE = 0.43       # backtest win-rate, shown as ml_prob (no trained model)
# Score = BASE + (age - MIN_AGE)*STEP so qualifying signals are slot-competitive with strong
# Baseline/MR scores and rank INTERNALLY by oversold depth (the validated dimension). Tunable:
# raising BASE prioritizes deep-oversold for the shared paper slots; lowering it defers to the
# legacy strategies. BASE=14.5 = the "HIGH" signal-strength tier (top ~5%).
DEEP_OVERSOLD_BASE_SCORE = 14.5
DEEP_OVERSOLD_AGE_STEP = 1.5

# ---------------------------------------------------------------------------
# Regime-aware parameter profiles
# Derived from assumption_tester v2 research (2000 trades, 100 dates).
# Key finding: bearish regimes favor wide stops (let bounces develop),
# bullish regimes favor tight stops (cut fast, upside is modest).
# ---------------------------------------------------------------------------
REGIME_PROFILES = {
    "Bearish": {
        "stop_multiplier_baseline": 2.5,
        "target_multiplier_baseline": 3.5,
        "stop_multiplier_mean_reversion": 2.0,
        "target_multiplier_mean_reversion": 2.5,
        "hold_days": 7,
        "max_positions_pct": 1.0,
    },
    "Neutral": {
        "stop_multiplier_baseline": 2.0,
        "target_multiplier_baseline": 3.0,
        "stop_multiplier_mean_reversion": 1.5,
        "target_multiplier_mean_reversion": 2.0,
        "hold_days": 5,
        "max_positions_pct": 1.0,
    },
    "Bullish": {
        "stop_multiplier_baseline": 1.5,
        "target_multiplier_baseline": 2.5,
        "stop_multiplier_mean_reversion": 1.0,
        "target_multiplier_mean_reversion": 1.5,
        "hold_days": 5,
        "max_positions_pct": 0.75,
    },
}

# ---------------------------------------------------------------------------
# Intraday Context Layer (Phase 1)
# Strategy-level multiplier applied to context_score before adding to total.
# Signal-level weights live in intraday_context.py.
# ---------------------------------------------------------------------------
INTRADAY_CONTEXT_WEIGHT = 6.0
INTRADAY_CONTEXT_WEIGHT_MR = 4.0
