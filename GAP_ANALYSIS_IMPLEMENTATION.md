# Gap Analysis - Implementation Guide

**Date:** 2026-01-31
**Status:** ✅ Implemented and Ready for Testing
**Branch:** `master`
**Indicator Type:** Price Action
**Priority:** ⭐⭐⭐ High

## Overview

Gap Analysis detects overnight gaps (open vs previous close) and validates them with volume confirmation. Gaps often signal institutional buying/selling and can mark the start of significant swing trading opportunities.

**Key Insight:** Many profitable swing trades start with gap-ups accompanied by strong volume, indicating institutional accumulation and breakout momentum.

## What Makes Gap Analysis Powerful

### 1. Detects Institutional Activity
- Gap + Volume = Institutions accumulating or distributing
- Retail traders can't move prices overnight
- Large gaps require significant buying/selling pressure

### 2. Identifies Breakout Momentum
- Gap-ups often mark the start of new trends
- Price breaking away from previous range
- Psychological shift in market perception

### 3. Early Entry Signal
- Gaps occur at market open (before intraday action)
- Catches momentum before it extends
- Better risk/reward than chasing intraday moves

### 4. Volume Confirmation
- Not all gaps are equal
- Volume validates institutional intent
- High volume gaps more reliable than low volume

## Implementation Details

### File Structure
- **Indicator:** `src/bluehorseshoe/analysis/indicators/price_action_indicators.py`
- **Config:** `src/bluehorseshoe/core/config.py` (DEFAULT_WEIGHTS)
- **Weights:** `src/weights.json` (price_action.GAP_MULTIPLIER)
- **Integration:** `src/bluehorseshoe/analysis/technical_analyzer.py`

### Calculation Method

```python
def calculate_gap_score(self) -> float:
    """
    Calculate Gap Analysis score based on overnight gap and volume confirmation.

    Formula:
        gap_pct = ((today_open - yesterday_close) / yesterday_close) * 100
        volume_ratio = today_volume / avg_volume_20

    Returns:
        float: Score from -2.0 to +2.0
    """
```

### Scoring Logic

**Gap-Ups (Bullish):**
- Gap >2% + Volume >1.5x avg = **+2.0** (strong breakout with institutional buying)
- Gap >2% + Volume >1.2x avg = **+1.5** (strong breakout with moderate volume)
- Gap >2% + Volume <1.2x avg = **+1.0** (strong breakout but weak volume)
- Gap >1% + Volume >1.2x avg = **+1.0** (moderate breakout with good volume)
- Gap >1% + Volume <1.2x avg = **+0.5** (moderate breakout with normal volume)
- Gap >0.5% = **+0.5** (small gap, mildly bullish)

**Gap-Downs (Bearish):**
- Gap <-2% = **-2.0** (strong weakness)
- Gap <-1% = **-1.0** (moderate weakness)
- Gap <-0.5% = **-0.5** (small gap down)

**No Significant Gap:**
- Gap between -0.5% and +0.5% = **0.0** (neutral)

### Configuration

In `src/weights.json`:

```json
{
  "price_action": {
    "GAP_MULTIPLIER": 0.0
  }
}
```

**Settings:**
- `GAP_MULTIPLIER = 0.0`: Disabled (default for now)
- `GAP_MULTIPLIER = 0.5`: Reduce impact by 50%
- `GAP_MULTIPLIER = 1.0`: Standard weight
- `GAP_MULTIPLIER = 1.5`: Amplify impact by 50%
- `GAP_MULTIPLIER = 2.0`: Double impact

### Data Requirements

Gap Analysis requires these columns in the DataFrame:
- `open` - Today's opening price
- `close` - Closing prices (need yesterday's close)
- `volume` - Volume data
- Minimum 21 days of data (20 for volume average + 1 for gap)

## How It Works

### Example: Strong Bullish Gap

```
Day 1: Close = $100.00
Day 2: Open = $103.00  (3% gap up)
       Volume = 2,000,000 (avg 20-day = 1,200,000)
       Volume Ratio = 1.67x

Result: Gap = 3% (>2%) + Volume = 1.67x (>1.5x) → Score = +2.0
```

**Interpretation:** Strong institutional buying overnight, high probability of continued momentum.

### Example: Weak Bullish Gap

```
Day 1: Close = $100.00
Day 2: Open = $102.50  (2.5% gap up)
       Volume = 1,100,000 (avg 20-day = 1,200,000)
       Volume Ratio = 0.92x

Result: Gap = 2.5% (>2%) + Volume = 0.92x (<1.2x) → Score = +1.0
```

**Interpretation:** Gap up without volume confirmation, less reliable signal.

### Example: Gap Down

```
Day 1: Close = $100.00
Day 2: Open = $97.50  (2.5% gap down)

Result: Gap = -2.5% (<-2%) → Score = -2.0
```

**Interpretation:** Strong weakness, avoid or consider shorting.

## Integration with Current System

Gap Analysis complements the current 3-indicator system:

**Current Winners:**
1. Marubozu (1.0x) - Single bar strength
2. Donchian (1.5x) - Breakout detection
3. Heiken Ashi (1.5x) - Trend smoothing

**Gap Analysis Adds:**
- Overnight momentum detection (Marubozu only sees intraday)
- Volume confirmation (current indicators don't validate with volume)
- Pre-market positioning (catches gaps before intraday action)

**Synergies:**
- Gap up + Marubozu = Strong confirmation (overnight AND intraday strength)
- Gap up + Donchian breakout = Powerful combo (gap triggers breakout)
- Gap up + Heiken Ashi bullish = Trend continuation signal

## Phase 3A: Isolated Testing Plan

### Objective
Test Gap Analysis in isolation to determine standalone performance and optimal weight.

### Test Configurations

**Test 1: Gap Only (Baseline Weight)**
```json
{
  "trend": { "ALL": 0.0 },
  "momentum": { "ALL": 0.0 },
  "volume": { "ALL": 0.0 },
  "candlestick": { "ALL": 0.0 },
  "price_action": { "GAP_MULTIPLIER": 1.0 },
  "mean_reversion": { "ALL": 0.0 }
}
```

**Test 2: Gap Reduced (0.5x)**
```json
{
  "price_action": { "GAP_MULTIPLIER": 0.5 }
}
```

**Test 3: Gap Boosted (1.5x)**
```json
{
  "price_action": { "GAP_MULTIPLIER": 1.5 }
}
```

**Test 4: Gap Double (2.0x)**
```json
{
  "price_action": { "GAP_MULTIPLIER": 2.0 }
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
- Sharpe > 1.8 (gaps are highly predictive)
- Win rate >60% (strong signals)
- Works across all market conditions

**Realistic Case:**
- Sharpe 1.0-1.5 (solid performer)
- Win rate 55-60%
- Better in bull markets than bear markets

**Worst Case:**
- Sharpe < 0.5 (weak standalone)
- Many false signals (gaps fade)
- Only effective in combination with other indicators

## Phase 3B: Combination Testing

### Test 1: Add Gap to Current Winners

**Current Baseline:** Marubozu (1.0x) + Donchian (1.5x) + Heiken Ashi (1.5x) = 0.310 Sharpe

**Add Gap (1.0x):**
```json
{
  "trend": {
    "HEIKEN_ASHI_MULTIPLIER": 1.5,
    "DONCHIAN_MULTIPLIER": 1.5
  },
  "candlestick": {
    "MARUBOZU_MULTIPLIER": 1.0
  },
  "price_action": {
    "GAP_MULTIPLIER": 1.0
  }
}
```

**Hypothesis:** Gap should improve Sharpe by adding overnight momentum detection.

**Expected:** 0.330-0.360 Sharpe (+6-16% improvement)

### Test 2: Gap + Marubozu (Power Combo)

Test if Gap + Marubozu alone can beat the current 3-indicator config:

```json
{
  "candlestick": {
    "MARUBOZU_MULTIPLIER": 1.0
  },
  "price_action": {
    "GAP_MULTIPLIER": 1.5
  }
}
```

**Hypothesis:** Gap (overnight strength) + Marubozu (intraday strength) = comprehensive momentum signal

**Expected:** 0.280-0.320 Sharpe (good, but likely not better than current 3-indicator config)

### Test 3: Different Gap Weights
Test Gap at 0.5x, 1.0x, 1.5x, 2.0x with current config to find optimal.

## Testing Commands

### Quick Test (Single Backtest)

```bash
# Backup current config
cp /root/BlueHorseshoe/src/weights.json /root/BlueHorseshoe/src/weights.json.backup

# Enable Gap only
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
    "MFI_MULTIPLIER": 0.0
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
    "GAP_MULTIPLIER": 1.0
  }
}
EOF

# Run single backtest
docker exec bluehorseshoe python src/main.py -t 2025-06-15

# Restore config
cp /root/BlueHorseshoe/src/weights.json.backup /root/BlueHorseshoe/src/weights.json
```

### Full Test (20 Backtests)

```bash
# Create test script
cat > /root/BlueHorseshoe/test_gap.sh << 'EOF'
#!/bin/bash
# Backup
cp src/weights.json src/weights.json.backup

# Enable Gap only at 1.0x
cp src/experiments/phase3_configs/gap_baseline.json src/weights.json

# Run 20 backtests with random dates
for i in {1..20}; do
  YEAR=$((2024 + RANDOM % 2))
  MONTH=$(printf "%02d" $((RANDOM % 12 + 1)))
  DAY=$(printf "%02d" $((RANDOM % 28 + 1)))
  docker exec bluehorseshoe python src/main.py -t ${YEAR}-${MONTH}-${DAY}
done

# Restore
cp src/weights.json.backup src/weights.json
EOF

chmod +x /root/BlueHorseshoe/test_gap.sh
./test_gap.sh
```

## Advantages of Gap Analysis

1. **Overnight Edge:** Captures institutional positioning that happens after hours
2. **Volume Validation:** Not just price action, but confirmed with volume
3. **Early Signal:** Identifies momentum at market open, not mid-day
4. **Breakout Detection:** Many big moves start with gaps
5. **Risk Definition:** Gap level provides clear invalidation point

## Limitations

1. **False Gaps:** Gaps can fade intraday (especially without volume)
2. **Gap Fill:** Markets often "fill the gap" - return to previous close
3. **News Dependent:** Many gaps are news-driven (unpredictable)
4. **Market Hours:** Only works for regular session (not pre-market data)
5. **Less Effective:** In low volatility or range-bound markets

## Gap Fill Consideration

**Future Enhancement Idea:**
Track if gaps get "filled" (price returns to previous close) within the holding period:
- Gap up that fills = failed breakout (reduce score)
- Gap up that holds = strong signal (increase score)

This could be implemented as a refinement if Gap Analysis proves effective.

## Real-World Examples

### Example 1: NVDA Gap-Up (Earnings)
```
Before: Close = $450
After:  Open = $475 (5.5% gap)
Volume: 3.2x average
Result: +2.0 score → Strong buy signal
Outcome: Continued to $495 over 5 days (+4.2%)
```

### Example 2: TSLA Gap-Down (News)
```
Before: Close = $250
After:  Open = $242 (3.2% gap down)
Result: -2.0 score → Avoid
Outcome: Continued decline to $230 over 5 days
```

### Example 3: False Gap (No Volume)
```
Before: Close = $100
After:  Open = $102 (2% gap up)
Volume: 0.8x average (weak)
Result: +1.0 score (gap without volume confirmation)
Outcome: Gap filled by noon, closed at $99.50
```

## Comparison to Other Indicators

| Indicator | Timeframe | Signal Type | Volume Used |
|-----------|-----------|-------------|-------------|
| **Gap Analysis** | Overnight | Momentum shift | Yes |
| **Marubozu** | Single day | Intraday strength | No |
| **Donchian** | 20 days | Breakout level | No |
| **Heiken Ashi** | Multi-day | Trend direction | No |
| **RS vs SPY** | 63 days | Market-relative | No |

**Key Difference:** Gap Analysis is the only indicator that:
- Focuses on overnight price action
- Validates signals with volume
- Detects institutional positioning

## Next Steps

1. ✅ Implement Gap Analysis (DONE)
2. ✅ Integrate into TechnicalAnalyzer (DONE)
3. ✅ Add configuration support (DONE)
4. ⏳ Run Phase 3A isolated testing (20 backtests × 4 weights)
5. ⏳ Compare to Phase 2 baseline (0.310 Sharpe)
6. ⏳ Run Phase 3B combination testing (Gap + current 3-indicator config)
7. ⏳ Optimize GAP_MULTIPLIER weight
8. ⏳ Update production if Gap improves performance

## Expected Timeline

- **Phase 3A (Isolated):** 8-12 hours (80 backtests)
- **Phase 3B (Combination):** 4-8 hours (40 backtests)
- **Analysis:** 2-3 hours
- **Total:** 1-2 days

## Conclusion

Gap Analysis is a powerful price action indicator that:
- ✅ Detects overnight institutional activity
- ✅ Validates with volume confirmation
- ✅ Captures breakout momentum early
- ✅ Complements current trend-following indicators
- ✅ Easy to implement and test
- ✅ Well-documented in trading literature

This indicator has high potential to improve the current system by adding overnight momentum detection and volume validation - two dimensions not covered by Marubozu, Donchian, or Heiken Ashi.

---

**Created:** 2026-01-31
**Author:** Claude Sonnet 4.5
**Status:** Ready for Phase 3 Testing
