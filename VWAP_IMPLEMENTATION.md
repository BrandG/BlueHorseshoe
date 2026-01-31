# VWAP (Volume Weighted Average Price) - Implementation Guide

**Date:** 2026-01-31
**Status:** ✅ Implemented and Ready for Testing
**Branch:** `master`
**Indicator Type:** Volume
**Priority:** ⭐⭐⭐ High

## Overview

VWAP (Volume Weighted Average Price) shows the average price weighted by volume, representing where institutional money is positioned. It's a critical benchmark used by institutional traders to evaluate execution quality and identify support/resistance levels.

**Key Insight:** Price above VWAP = institutional buying pressure. Price below VWAP = institutional selling pressure or weak hands.

## What Makes VWAP Powerful

### 1. Institutional Benchmark
- Professional traders use VWAP as execution benchmark
- Institutions try to fill orders near/below VWAP (minimize slippage)
- Price consistently above VWAP = strong institutional support

### 2. Dynamic Support/Resistance
- VWAP acts as magnet for price
- Price above VWAP tends to find support at VWAP
- Price below VWAP faces resistance at VWAP

### 3. Volume-Weighted (Better than Simple MA)
- Weights price by volume at each level
- Reflects where "real" trading occurred
- More representative than simple moving average

### 4. Market Psychology
- Traders who bought below VWAP are profitable
- Traders who bought above VWAP are underwater
- Crossing VWAP shifts psychology

## Implementation Details

### File Structure
- **Indicator:** `src/bluehorseshoe/analysis/indicators/volume_indicators.py`
- **Config:** `src/bluehorseshoe/core/config.py` (DEFAULT_WEIGHTS)
- **Weights:** `src/weights.json` (volume.VWAP_MULTIPLIER)
- **Tests:** `src/bluehorseshoe/analysis/indicators/tests/test_vwap.py`

### Calculation Method

Since we only have daily OHLCV data (not intraday tick data), we use an approximation:

```python
def calculate_vwap(self, window: int = 20) -> float:
    """
    Calculate VWAP over N days.

    Formula:
        Typical Price = (High + Low + Close) / 3
        VWAP = Sum(Typical Price × Volume) / Sum(Volume) over window

    Returns:
        float: Score from -2.0 to +2.0
    """
```

**Note:** True intraday VWAP requires tick data and resets daily. Our daily VWAP approximation uses a rolling window (default 20 days) as a proxy for institutional average entry price.

### Scoring Logic

**Price Above VWAP (Bullish):**
- Price >2% above VWAP = **+2.0** (strong institutional support)
- Price >1% above VWAP = **+1.0** (above institutional average)

**Price Near VWAP (Neutral):**
- Price within ±1% of VWAP = **0.0** (neutral, at equilibrium)

**Price Below VWAP (Bearish):**
- Price <1% below VWAP = **-1.0** (below institutional average)
- Price <2% below VWAP = **-2.0** (weak institutional support)

### Configuration

In `src/weights.json`:

```json
{
  "volume": {
    "VWAP_MULTIPLIER": 0.0
  }
}
```

**Settings:**
- `VWAP_MULTIPLIER = 0.0`: Disabled (default for now)
- `VWAP_MULTIPLIER = 0.5`: Reduce impact by 50%
- `VWAP_MULTIPLIER = 1.0`: Standard weight
- `VWAP_MULTIPLIER = 1.5`: Amplify impact by 50%
- `VWAP_MULTIPLIER = 2.0`: Double impact

### Data Requirements

VWAP requires these columns in the DataFrame:
- `high` - Daily high prices
- `low` - Daily low prices
- `close` - Daily closing prices
- `volume` - Volume data
- Minimum 20 days of data (for default window)

## How It Works

### Example 1: Strong Institutional Support

```
20-Day Period:
  Days 1-10:  Price avg $95, Volume avg 1M shares
  Days 11-20: Price avg $100, Volume avg 1.5M shares (increased institutional buying)

VWAP Calculation:
  Typical Price = (High + Low + Close) / 3
  VWAP = Sum(Typical Price × Volume) / Sum(Volume)
  VWAP ≈ $97.86

Current Price: $100.00
Difference: ($100 - $97.86) / $97.86 = +2.18%

Result: Price >2% above VWAP → Score = +2.0
```

**Interpretation:** Stock is well above institutional average entry. Strong hands holding, likely to continue up.

### Example 2: Weak Institutional Support

```
20-Day Period:
  Days 1-10:  Price avg $105, Volume avg 2M shares (heavy distribution)
  Days 11-20: Price avg $98, Volume avg 800K shares (low interest)

VWAP ≈ $102.14

Current Price: $97.50
Difference: ($97.50 - $102.14) / $102.14 = -4.55%

Result: Price <2% below VWAP → Score = -2.0
```

**Interpretation:** Stock is well below institutional average. Many holders underwater, likely selling pressure.

### Example 3: At Equilibrium

```
20-Day Period:
  Stable trading around $50, consistent volume

VWAP ≈ $50.12

Current Price: $50.25
Difference: ($50.25 - $50.12) / $50.12 = +0.26%

Result: Price within ±1% of VWAP → Score = 0.0
```

**Interpretation:** Price at fair value. Neutral positioning.

## Integration with Current System

VWAP complements the current 3-indicator system:

**Current Winners:**
1. Marubozu (1.0x) - Single bar strength
2. Donchian (1.5x) - Breakout detection
3. Heiken Ashi (1.5x) - Trend smoothing

**VWAP Adds:**
- Volume-weighted price context (current indicators don't weight by volume)
- Institutional positioning (shows where "smart money" entered)
- Dynamic support/resistance (VWAP acts as magnet)

**Synergies:**
- Donchian breakout + Price above VWAP = Breakout with institutional support
- Marubozu + Price >2% above VWAP = Strong momentum with strong hands
- Heiken Ashi uptrend + VWAP rising = Sustained institutional accumulation

## Phase 3A: Isolated Testing Plan

### Objective
Test VWAP in isolation to determine standalone performance and optimal weight.

### Test Configurations

**Test 1: VWAP Only (Baseline Weight)**
```json
{
  "trend": { "ALL": 0.0 },
  "momentum": { "ALL": 0.0 },
  "volume": { "VWAP_MULTIPLIER": 1.0, "ALL_OTHERS": 0.0 },
  "candlestick": { "ALL": 0.0 },
  "price_action": { "ALL": 0.0 },
  "mean_reversion": { "ALL": 0.0 }
}
```

**Test 2: VWAP Reduced (0.5x)**
```json
{
  "volume": { "VWAP_MULTIPLIER": 0.5 }
}
```

**Test 3: VWAP Boosted (1.5x)**
```json
{
  "volume": { "VWAP_MULTIPLIER": 1.5 }
}
```

**Test 4: VWAP Double (2.0x)**
```json
{
  "volume": { "VWAP_MULTIPLIER": 2.0 }
}
```

### Testing Methodology
- **Runs per config:** 20 backtests
- **Date range:** Random dates from 2024-01-01 to 2026-01-27
- **Symbols:** 1,000 random per run
- **Hold period:** 5 days
- **Top candidates:** 5 per backtest

### Success Criteria
- **Strong Performer:** Sharpe > 1.5
- **Moderate Performer:** Sharpe 0.8-1.5
- **Weak Performer:** Sharpe < 0.5

### Expected Outcomes

**Best Case:**
- Sharpe > 1.8 (VWAP highly predictive)
- Win rate >60%
- Low drawdown (VWAP provides support)

**Realistic Case:**
- Sharpe 1.0-1.5 (solid performer)
- Win rate 55-60%
- Better in trending markets than choppy markets

**Worst Case:**
- Sharpe < 0.5 (weak standalone)
- Better as confirmation than primary signal
- Only effective in combination with other indicators

## Phase 3B: Combination Testing

### Test 1: Add VWAP to Current Winners

**Current Baseline:** Marubozu (1.0x) + Donchian (1.5x) + Heiken Ashi (1.5x) = 0.310 Sharpe

**Add VWAP (1.0x):**
```json
{
  "trend": {
    "HEIKEN_ASHI_MULTIPLIER": 1.5,
    "DONCHIAN_MULTIPLIER": 1.5
  },
  "volume": {
    "VWAP_MULTIPLIER": 1.0
  },
  "candlestick": {
    "MARUBOZU_MULTIPLIER": 1.0
  }
}
```

**Hypothesis:** VWAP should improve Sharpe by adding volume-weighted institutional positioning.

**Expected:** 0.330-0.360 Sharpe (+6-16% improvement)

### Test 2: VWAP + Volume Powerhouse

Test if combining VWAP with OBV creates superior volume-based system:

```json
{
  "volume": {
    "VWAP_MULTIPLIER": 1.0,
    "OBV_MULTIPLIER": 1.0
  }
}
```

**Note:** From Phase 1, OBV had 2.379 Sharpe (excellent). Testing if VWAP + OBV together is even better.

**Expected:** Sharpe 1.8-2.5 (may be redundant or may be synergistic)

### Test 3: Different VWAP Windows
Test VWAP at different lookback periods:
- 10 days (short-term institutional positioning)
- 20 days (default, ~1 month)
- 50 days (longer-term institutional positioning)

## Advantages of VWAP

1. **Institutional Benchmark** - Used by professionals worldwide
2. **Volume-Weighted** - More meaningful than simple price averages
3. **Dynamic** - Adapts to changing volume patterns
4. **Support/Resistance** - Acts as magnet for price
5. **Risk Management** - Helps identify underwater vs profitable positions
6. **Proven Track Record** - Decades of institutional use

## Limitations

1. **Daily Approximation** - True VWAP requires intraday tick data
2. **Lagging Indicator** - Based on past prices/volume
3. **Window Sensitivity** - Different windows give different results
4. **Choppy Markets** - Less effective in sideways/volatile markets
5. **Not Direction Signal** - Shows positioning, not future direction

## VWAP vs Other Volume Indicators

| Indicator | What It Measures | Data Required | Timeframe |
|-----------|------------------|---------------|-----------|
| **VWAP** | Volume-weighted avg price | OHLCV | 20 days (rolling) |
| **OBV** | Cumulative volume flow | Close, Volume | All history |
| **CMF** | Money flow over period | OHLCV | 20 days |
| **MFI** | Money flow index (RSI-like) | OHLCV | 14 days |

**Key Difference:** VWAP is the only indicator that:
- Weights price by volume at each level
- Represents institutional average entry price
- Used as execution benchmark by professionals

## Real-World Usage

### Intraday Traders
- Buy when price dips to VWAP (support)
- Sell when price reaches VWAP from below (resistance)
- Use VWAP as stop-loss reference

### Institutional Traders
- Try to execute large orders near VWAP (minimize market impact)
- Track VWAP to measure execution quality
- Report "VWAP performance" to clients

### Swing Traders (Our Use Case)
- Buy stocks above VWAP (institutional support)
- Avoid stocks below VWAP (weak hands)
- Use VWAP distance as confirmation signal

## Testing Commands

### Quick Test (Single Backtest)

```bash
# Backup current config
cp /root/BlueHorseshoe/src/weights.json /root/BlueHorseshoe/src/weights.json.backup

# Enable VWAP only
cat > /root/BlueHorseshoe/src/weights.json << 'EOF'
{
  "trend": {
    "ADX_MULTIPLIER": 0.0,
    "STOCHASTIC_MULTIPLIER": 0.0,
    "ICHIMOKU_MULTIPLIER": 0.0,
    "PSAR_MULTIPLIER": 0.0,
    "HEIKEN_ASHI_MULTIPLIER": 0.0,
    "DONCHIAN_MULTIPLIER": 0.0,
    "SUPERTREND_MULTIPLIER": 0.0
  },
  "momentum": {
    "RSI_MULTIPLIER": 0.0,
    "ROC_MULTIPLIER": 0.0,
    "MACD_MULTIPLIER": 0.0,
    "MACD_SIGNAL_MULTIPLIER": 0.0,
    "BB_MULTIPLIER": 0.0,
    "WILLIAMS_R_MULTIPLIER": 0.0,
    "CCI_MULTIPLIER": 0.0,
    "RS_MULTIPLIER": 0.0
  },
  "volume": {
    "OBV_MULTIPLIER": 0.0,
    "CMF_MULTIPLIER": 0.0,
    "ATR_BAND_MULTIPLIER": 0.0,
    "ATR_SPIKE_MULTIPLIER": 0.0,
    "MFI_MULTIPLIER": 0.0,
    "VWAP_MULTIPLIER": 1.0
  },
  "candlestick": {
    "RISE_FALL_3_METHODS_MULTIPLIER": 0.0,
    "THREE_WHITE_SOLDIERS_MULTIPLIER": 0.0,
    "MARUBOZU_MULTIPLIER": 0.0,
    "BELT_HOLD_MULTIPLIER": 0.0
  },
  "mean_reversion": {
    "RSI_MULTIPLIER": 0.0,
    "BB_MULTIPLIER": 0.0,
    "MA_DIST_MULTIPLIER": 0.0,
    "CANDLESTICK_MULTIPLIER": 0.0
  },
  "price_action": {
    "GAP_MULTIPLIER": 0.0
  }
}
EOF

# Run single backtest
docker exec bluehorseshoe python src/main.py -t 2025-06-15

# Restore config
cp /root/BlueHorseshoe/src/weights.json.backup /root/BlueHorseshoe/src/weights.json
```

## Optimization Opportunities

### 1. Dynamic Window
Adjust window based on volatility:
- High volatility = shorter window (10 days)
- Low volatility = longer window (50 days)

### 2. VWAP Slope
Track if VWAP is rising or falling:
- Rising VWAP = sustained accumulation
- Falling VWAP = sustained distribution

### 3. VWAP Bands
Create standard deviation bands around VWAP:
- Price at upper band = overbought vs institutions
- Price at lower band = oversold vs institutions

### 4. Multi-Timeframe VWAP
Combine short (10d), medium (20d), long (50d) VWAP:
- All aligned = strong trend
- Diverging = trend weakening

## Comparison to Phase 1 Volume Indicators

From Phase 1 testing, OBV performed exceptionally well:

| Indicator | Optimal Weight | Sharpe | Win Rate | Notes |
|-----------|---------------|---------|----------|-------|
| **OBV** | 1.0x | 2.379 | 64.63% | Elite performer |
| **CMF** | 1.5x | 1.200 | 60.47% | Strong performer |
| **VWAP** | TBD | TBD | TBD | Now testing |

**Question:** Can VWAP match or beat OBV's performance? OBV is cumulative (all history), VWAP is rolling window (20 days). Different approaches to volume analysis.

## Next Steps

1. ✅ Implement VWAP calculation (DONE)
2. ✅ Add to VolumeIndicator class (DONE)
3. ✅ Create unit tests (8/8 passing)
4. ✅ Add configuration support (DONE)
5. ⏳ Run Phase 3A isolated testing (20 backtests × 4 weights)
6. ⏳ Compare to OBV and CMF (Phase 1 results)
7. ⏳ Run Phase 3B combination testing (VWAP + current 3-indicator config)
8. ⏳ Optimize VWAP_MULTIPLIER and window size
9. ⏳ Update production if VWAP improves performance

## Expected Timeline

- **Phase 3A (Isolated):** 8-12 hours (80 backtests)
- **Phase 3B (Combination):** 4-8 hours (40 backtests)
- **Analysis:** 2-3 hours
- **Total:** 1-2 days

## Conclusion

VWAP is a powerful, institutional-grade indicator that:
- ✅ Shows volume-weighted average price (institutional positioning)
- ✅ Acts as dynamic support/resistance
- ✅ Used by professional traders worldwide
- ✅ Complements current trend-following indicators
- ✅ Different from existing volume indicators (OBV, CMF)
- ✅ Well-tested with 8 passing unit tests

This indicator has high potential to improve the current system by adding institutional positioning context - a dimension not directly captured by Marubozu, Donchian, Heiken Ashi, or even OBV/CMF.

**Key Question:** Will VWAP's volume-weighting approach beat OBV's cumulative approach? Phase 3A testing will reveal the answer.

---

**Created:** 2026-01-31
**Author:** Claude Sonnet 4.5
**Status:** Ready for Phase 3 Testing
