# Relative Strength (RS) vs SPY - Implementation Guide

**Date:** 2026-01-30
**Status:** ✅ Implemented and Configurable
**Branch:** `master`
**Indicator Type:** Momentum / Market-Relative

## Overview

Relative Strength (RS) compares a stock's performance to the S&P 500 (SPY) benchmark over a lookback period. Stocks outperforming the market (RS > 1.0) are market leaders and preferred candidates for swing trading.

**Key Insight:** We want to buy the strongest stocks, not just trending stocks. RS filters for market leadership.

## What Makes RS Powerful

### 1. Identifies Market Leaders
- RS > 1.5 = Stock up 50% more than market (exceptional)
- RS > 1.2 = Stock up 20% more than market (strong)
- RS > 1.0 = Outperforming market (leader)
- RS < 1.0 = Underperforming market (laggard)

### 2. Used by Proven Systems
- **IBD (Investor's Business Daily):** Core metric in their CAN SLIM system
- **Mark Minervini:** SEPA methodology depends on relative strength
- **William O'Neil:** "Buy the leaders, avoid the laggards"

### 3. Complements Trend Following
- A stock can be in an uptrend but underperforming the market
- RS ensures we're buying strength, not just momentum
- During corrections, RS > 1.0 stocks hold up better

## Implementation Details

### Current Scoring Logic

Located in: `src/bluehorseshoe/analysis/strategy.py` (lines 368-378)

```python
# Apply Relative Strength (RS) Bonus
rs_multiplier = weights_config.get_weights('momentum').get('RS_MULTIPLIER', 1.0)
if ctx.benchmark_df is not None and rs_multiplier != 0.0:
    rs_ratio = self.calculate_relative_strength(df, ctx.benchmark_df)
    if rs_ratio > 1.10:
        rs_bonus = 5.0  # Strong outperformance
    elif rs_ratio > 1.0:
        rs_bonus = 2.0  # Outperforming
    else:
        rs_bonus = -2.0  # Underperforming (penalty)
    rs_bonus *= rs_multiplier
    score_components["rs_index"] = rs_bonus
    score_components["total"] += rs_bonus
```

### Calculation Method

Located in: `src/bluehorseshoe/analysis/strategy.py` (line 281)

```python
def calculate_relative_strength(self, df: pd.DataFrame, benchmark_df: pd.DataFrame, lookback: int = 63) -> float:
    """
    Calculates Relative Strength (RS) ratio of the stock vs the benchmark.
    A value > 1.0 means the stock is outperforming the benchmark over the lookback period.
    Default lookback is 63 trading days (~3 months).
    """
    if len(df) < lookback or len(benchmark_df) < lookback:
        return 1.0

    stock_perf = df['close'].iloc[-1] / df['close'].iloc[-lookback]
    bench_perf = benchmark_df['close'].iloc[-1] / benchmark_df['close'].iloc[-lookback]

    return stock_perf / bench_perf if bench_perf > 0 else 1.0
```

**Formula:** `RS = (Stock % Change) / (SPY % Change)` over 63 days

### Configuration

In `src/weights.json`:

```json
{
  "momentum": {
    ...
    "RS_MULTIPLIER": 1.0
  }
}
```

**Settings:**
- `RS_MULTIPLIER = 0.0`: Disable RS (no bonus/penalty)
- `RS_MULTIPLIER = 0.5`: Reduce RS impact by 50%
- `RS_MULTIPLIER = 1.0`: Current production (default)
- `RS_MULTIPLIER = 1.5`: Amplify RS impact by 50%
- `RS_MULTIPLIER = 2.0`: Double RS impact

## Current Production Impact

With `RS_MULTIPLIER = 1.0` (default):
- **RS > 1.10:** +5.0 points added to baseline score
- **RS > 1.0:** +2.0 points added to baseline score
- **RS ≤ 1.0:** -2.0 points (penalty for underperformers)

This means:
- Market leaders get significant bonus
- Market laggers get penalty (filtered out)
- Only applies to baseline (trend-following) strategy

## Phase 3A: Isolated Testing Plan

### Objective
Test RS in isolation to determine if it's a positive performer and find its optimal weight.

### Test Configuration

**Test 1: RS Only (Baseline Weight)**
```json
{
  "trend": { "ALL": 0.0 },
  "momentum": { "RS_MULTIPLIER": 1.0, "ALL_OTHERS": 0.0 },
  "volume": { "ALL": 0.0 },
  "candlestick": { "ALL": 0.0 },
  "mean_reversion": { "ALL": 0.0 }
}
```

**Test 2: RS Reduced (0.5x)**
```json
{
  "momentum": { "RS_MULTIPLIER": 0.5, "ALL_OTHERS": 0.0 }
}
```

**Test 3: RS Boosted (1.5x)**
```json
{
  "momentum": { "RS_MULTIPLIER": 1.5, "ALL_OTHERS": 0.0 }
}
```

**Test 4: RS Double (2.0x)**
```json
{
  "momentum": { "RS_MULTIPLIER": 2.0, "ALL_OTHERS": 0.0 }
}
```

### Testing Methodology
- **Runs per config:** 20 backtests
- **Date range:** Random dates from 2024-01-01 to 2026-01-27
- **Symbols:** 1,000 random per run
- **Hold period:** 5 days
- **Top candidates:** 5 per backtest

### Success Criteria
- **Positive Sharpe:** RS > 0.5 Sharpe = viable indicator
- **High Win Rate:** RS > 55% win rate = strong signal
- **Low Drawdown:** RS < 30% max drawdown = good risk control

### Expected Outcomes

**Best Case:**
- RS Sharpe > 1.5 (strong standalone performer)
- High win rate (>60%) due to market leadership filter
- Low drawdown due to avoiding weak stocks

**Realistic Case:**
- RS Sharpe 0.8-1.2 (moderate performer)
- Win rate 55-60%
- Works best in bull markets, struggles in bear markets

**Worst Case:**
- RS Sharpe < 0.3 (weak standalone)
- RS only effective in combination with other indicators
- Needs trend confirmation to avoid false signals

## Phase 3B: Combination Testing

After isolated testing, test RS with current production config:

### Test 1: Add RS to Current Winners
Current: Marubozu (1.0x) + Donchian (1.5x) + Heiken Ashi (1.5x) = 0.310 Sharpe

**Add RS (1.0x):**
```json
{
  "trend": {
    "HEIKEN_ASHI_MULTIPLIER": 1.5,
    "DONCHIAN_MULTIPLIER": 1.5
  },
  "momentum": {
    "RS_MULTIPLIER": 1.0
  },
  "candlestick": {
    "MARUBOZU_MULTIPLIER": 1.0
  }
}
```

**Hypothesis:** RS should improve Sharpe by filtering for market leaders.

**Expected:** 0.330-0.350 Sharpe (+6-13% improvement)

### Test 2: Replace Weakest Indicator
If any of the 3 current indicators is weaker, try replacing it with RS.

### Test 3: Different RS Weights
Test RS at 0.5x, 1.0x, 1.5x, 2.0x with current config to find optimal.

## Data Requirements

### SPY Data Availability
- **Source:** Already loaded via `_load_benchmark_data()` in strategy.py
- **Requirement:** SPY must have 63+ trading days of data
- **Check:** `docker exec bluehorseshoe python -c "from bluehorseshoe.data.historical_data import load_historical_data; from bluehorseshoe.core.database import get_database; db = get_database(); data = load_historical_data('SPY', database=db); print(f'SPY data points: {len(data.get(\"days\", []))}')"`

### Ensure SPY is Updated
Before testing, ensure SPY has recent data:
```bash
docker exec bluehorseshoe python src/main.py -b --symbols SPY --limit 500
```

## Testing Commands

### Run Isolated Test (RS Only at 1.0x)

1. Create config file:
```bash
cat > /root/BlueHorseshoe/src/experiments/phase3_configs/rs_baseline.json << 'EOF'
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
    "RS_MULTIPLIER": 1.0
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
  }
}
EOF
```

2. Run backtest:
```bash
# Backup current weights
cp /root/BlueHorseshoe/src/weights.json /root/BlueHorseshoe/src/weights.json.backup

# Apply RS-only config
cp /root/BlueHorseshoe/src/experiments/phase3_configs/rs_baseline.json /root/BlueHorseshoe/src/weights.json

# Run 20 backtests
for i in {1..20}; do
  docker exec bluehorseshoe python src/main.py -t 2024-$(printf "%02d" $((RANDOM % 12 + 1)))-$(printf "%02d" $((RANDOM % 28 + 1)))
done

# Restore original weights
cp /root/BlueHorseshoe/src/weights.json.backup /root/BlueHorseshoe/src/weights.json
```

3. Analyze results:
```bash
docker exec bluehorseshoe python -c "
import pandas as pd
df = pd.read_csv('src/logs/backtest_log.csv')
recent = df.tail(100)  # Last 100 trades from RS tests
print(f'Win Rate: {recent[\"outcome\"].eq(\"win\").mean() * 100:.2f}%')
print(f'Avg P&L: {recent[\"pnl_percent\"].mean():.2f}%')
print(f'Total Trades: {len(recent)}')
"
```

## Advantages of RS

1. **Market Context:** Knows when a stock is leading vs lagging
2. **Risk Reduction:** Avoids stocks rotating out of favor
3. **Sector Rotation:** Catches stocks with institutional support
4. **Universally Proven:** Used by legendary traders (O'Neil, Minervini)

## Limitations

1. **Bull Market Bias:** RS favors rising markets (may underperform in bear)
2. **Requires SPY Data:** Dependent on benchmark data quality
3. **Lookback Sensitive:** 63-day window may miss very recent strength changes
4. **Not a Timing Tool:** RS shows relative performance, not entry timing

## Comparison to Other Indicators

| Indicator | What It Measures | Timeframe | Category |
|-----------|------------------|-----------|----------|
| **RS** | Stock vs market performance | 63 days | Relative |
| **RSI** | Overbought/oversold | 14 days | Absolute |
| **ROC** | Price momentum | 10 days | Absolute |
| **Donchian** | Breakout level | 20 days | Absolute |
| **Marubozu** | Single bar strength | 1 day | Absolute |

**Key Difference:** RS is the only indicator that compares stock performance to the broader market.

## Optimization Opportunities

### 1. Variable Lookback Periods
Test different windows:
- 20 days (1 month)
- 63 days (3 months) - current
- 126 days (6 months)
- 252 days (1 year)

### 2. Dynamic Thresholds
Instead of fixed 1.10/1.0 thresholds, use market-adjusted:
- Bull market: RS > 1.05 acceptable
- Bear market: RS > 1.20 required

### 3. RS Momentum
Track if RS is increasing/decreasing:
- RS rising = gaining strength (bonus)
- RS falling = losing strength (penalty)

### 4. Multi-Timeframe RS
Combine short-term (20d) and long-term (126d) RS:
- Both positive = sustained leadership
- Short > long = accelerating
- Short < long = decelerating

## Documentation References

- **Implementation:** `src/bluehorseshoe/analysis/strategy.py` (lines 281-293, 368-378)
- **Config:** `src/weights.json` (momentum.RS_MULTIPLIER)
- **Phase 3 Plan:** `PHASE3_NEXT_INDICATORS.md`
- **Testing Guide:** This document

## Next Steps

1. ✅ Make RS configurable via weights.json (DONE)
2. ⏳ Run Phase 3A isolated testing (20 backtests at 0.5x, 1.0x, 1.5x, 2.0x)
3. ⏳ Compare results to Phase 2 baseline (0.310 Sharpe)
4. ⏳ Run Phase 3B combination testing (RS + current 3-indicator config)
5. ⏳ Optimize RS_MULTIPLIER weight
6. ⏳ Update production config if RS improves performance

## Expected Timeline

- **Phase 3A (Isolated):** 8-12 hours (80 backtests)
- **Phase 3B (Combination):** 4-8 hours (40 backtests)
- **Analysis:** 2-3 hours
- **Total:** 1-2 days

## Conclusion

Relative Strength vs SPY is a powerful, proven indicator that:
- ✅ Already implemented in the codebase
- ✅ Now configurable via weights.json
- ✅ Ready for Phase 3 testing
- ✅ Addresses a fundamental gap (market-relative performance)
- ✅ Used by legendary traders and systems

This indicator has high potential to improve the current 3-indicator config by ensuring we only trade market leaders, not just trending stocks.

---

**Created:** 2026-01-30
**Author:** Claude Sonnet 4.5
**Status:** Ready for Phase 3 Testing
