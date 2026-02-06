# Phase 3: Next Generation Indicators

**Date:** 2026-01-30
**Status:** Planning
**Branch:** `master`

## Overview

After Phase 1 (isolated testing of 26 indicators) and Phase 2 (combination testing), we've identified a winning 3-indicator configuration:
- Marubozu (1.0x)
- Donchian Channels (1.5x)
- Heiken Ashi (1.5x)

This configuration achieves **0.310 Sharpe** (+91% improvement over 20-indicator config).

Phase 3 will explore powerful indicators not yet implemented in the system.

## Candidate Indicators (Priority Order)

### 1. Relative Strength vs Market (RS) ⭐⭐⭐ PRIORITY

**Category:** Momentum/Market-Relative
**Status:** ⏳ In Development

**Description:**
- Compares stock performance to SPY benchmark over lookback period
- Formula: `RS = (Stock % Change) / (SPY % Change)` over N days
- RS > 1.0 = outperforming market (leader)
- RS < 1.0 = underperforming market (laggard)

**Why It's Powerful:**
- Used by IBD (Investor's Business Daily) as their core metric
- Mark Minervini's SEPA methodology depends on relative strength
- Identifies market leaders vs followers
- **Gap in current system:** We select trending stocks, but don't verify they're stronger than the market

**Implementation Details:**
- Lookback periods to test: 20, 50, 100 days
- Requires SPY data in database
- Scoring:
  - RS > 1.5 (50% outperformance) = +2.0
  - RS > 1.2 (20% outperformance) = +1.0
  - RS > 1.0 (outperforming) = +0.5
  - RS < 0.8 (underperforming) = -1.0
  - RS < 0.5 (severe underperformance) = -2.0

**Expected Impact:** High - addresses fundamental gap in stock selection

---

### 2. Gap Analysis ⭐⭐⭐

**Category:** Price Action
**Status:** ⏳ Planned

**Description:**
- Measures overnight gap (open vs previous close)
- Gap direction + magnitude + volume confirmation
- Gap-ups with volume often signal institutional accumulation

**Why It's Powerful:**
- Many swing trades start from gap-up breakouts
- Combines price action + volume
- **Gap in current system:** Completely blind to overnight gaps

**Implementation Details:**
- Gap % = `(Open - Prev Close) / Prev Close * 100`
- Scoring:
  - Gap up >2% with volume >1.5x avg = +2.0
  - Gap up >1% with volume >1.2x avg = +1.0
  - Gap down >2% = -2.0
  - No gap or small gap = 0.0

**Expected Impact:** High - captures breakout momentum we currently miss

---

### 3. VWAP (Volume Weighted Average Price) ⭐⭐⭐

**Category:** Volume/Price
**Status:** ⏳ Planned

**Description:**
- Average price weighted by volume traded at each price level
- Institutional traders use VWAP as benchmark
- Price above VWAP = institutional strength
- Price below VWAP = institutional weakness

**Why It's Powerful:**
- Shows where institutional money is positioned
- Better than simple moving averages (volume-weighted)
- **Gap in current system:** OBV/CMF track flow but not price level where volume occurred

**Implementation Details:**
- Intraday VWAP: `Sum(Price × Volume) / Sum(Volume)` for the day
- Daily VWAP: Can use typical price weighted by volume
- Scoring:
  - Price >2% above VWAP = +2.0
  - Price >1% above VWAP = +1.0
  - Price <1% below VWAP = -1.0
  - Price <2% below VWAP = -2.0

**Note:** May require intraday data or approximation using daily bars

**Expected Impact:** Medium-High - institutional confirmation

---

### 4. TTM Squeeze (Bollinger/Keltner) ⭐⭐

**Category:** Volatility
**Status:** ⏳ Planned

**Description:**
- When Bollinger Bands compress inside Keltner Channels = "squeeze"
- Low volatility that precedes explosive moves
- Squeeze release = big directional move coming

**Why It's Powerful:**
- Identifies compression before expansion (coiled spring)
- Perfect for swing trading entries (buy at compression, exit at expansion)
- **Gap in current system:** We have BB but not the squeeze calculation

**Implementation Details:**
- Calculate Keltner Channels (EMA ± ATR * multiplier)
- Calculate Bollinger Bands (SMA ± Std Dev * multiplier)
- Squeeze = BB width < Keltner width
- Scoring:
  - In squeeze + price rising = +2.0 (coiling for breakout)
  - Just released from squeeze + momentum up = +1.5
  - In squeeze + price falling = -1.0
  - Wide bands (high volatility) = 0.0

**Expected Impact:** Medium - complements Donchian breakouts

---

### 5. Aroon Indicator ⭐⭐

**Category:** Trend
**Status:** ⏳ Planned

**Description:**
- Measures time since highest high / lowest low over period
- Aroon Up = `((Period - Days Since High) / Period) * 100`
- Aroon Down = `((Period - Days Since Low) / Period) * 100`
- Aroon Up crossing above Aroon Down = new uptrend

**Why It's Powerful:**
- Detects trend changes early (time-based, not price-based)
- Different approach than ADX, MACD, or other trend indicators
- **Gap in current system:** Different trend detection methodology

**Implementation Details:**
- Standard period: 25 days
- Scoring:
  - Aroon Up > 70 and Aroon Down < 30 = +2.0 (strong uptrend)
  - Aroon Up > 50 and rising = +1.0
  - Aroon Up crossed above Aroon Down recently = +1.5 (new trend)
  - Aroon Down > Aroon Up = -1.0

**Expected Impact:** Medium - alternative trend detection

---

### 6. Keltner Channels ⭐

**Category:** Trend/Volatility
**Status:** ⏳ Planned

**Description:**
- Similar to Bollinger Bands but uses ATR instead of standard deviation
- EMA ± (ATR * multiplier)
- Breakouts above upper Keltner = strong trend

**Why It's Powerful:**
- More stable than BB (ATR vs std dev)
- Some traders prefer it for breakout detection
- Required component for TTM Squeeze
- **Gap in current system:** We use BB but not Keltner

**Implementation Details:**
- Typical: 20-period EMA, 2.0 × ATR
- Scoring similar to BB:
  - Price > upper Keltner = +1.0
  - Price breaking above upper Keltner = +2.0
  - Price < lower Keltner = -1.0

**Expected Impact:** Low-Medium - may complement or replace BB

---

### 7. Elder's Force Index ⭐

**Category:** Volume/Momentum
**Status:** ⏳ Planned

**Description:**
- Formula: `(Close - Previous Close) × Volume`
- Measures the "power" behind price moves
- Combines price change and volume differently than OBV/CMF

**Why It's Powerful:**
- Shows force/power of buying/selling
- Created by Dr. Alexander Elder (Trading for a Living)
- **Gap in current system:** Different volume/price relationship than OBV/CMF

**Implementation Details:**
- Calculate 13-period EMA of Force Index
- Scoring:
  - Force Index > 0 and rising = +1.0
  - Force Index > 0 and accelerating = +2.0
  - Force Index < 0 and falling = -1.0
  - Force Index divergence (price up, FI down) = -2.0

**Expected Impact:** Low-Medium - may overlap with existing volume indicators

---

### 8. Accumulation/Distribution Line (A/D Line) ⭐

**Category:** Volume
**Status:** ⏳ Planned

**Description:**
- Similar to OBV but uses: `[(Close - Low) - (High - Close)] / (High - Low) × Volume`
- More sensitive to where price closes within the bar
- Cumulative indicator

**Why It's Powerful:**
- More nuanced than OBV (considers intraday position)
- Developed by Marc Chaikin (also created CMF)
- **Gap in current system:** OBV only uses close vs previous close

**Implementation Details:**
- Money Flow Multiplier: `[(Close - Low) - (High - Close)] / (High - Low)`
- Money Flow Volume: `Money Flow Multiplier × Volume`
- A/D Line: Cumulative sum of Money Flow Volume
- Scoring:
  - A/D rising over 5 days = +1.0
  - A/D rising over 10 days = +2.0
  - A/D divergence (price down, A/D up) = +1.5 (bullish)
  - A/D falling = -1.0

**Expected Impact:** Low - may be redundant with OBV/CMF

---

## Testing Strategy

### Phase 3A: Isolated Testing
1. Implement each indicator
2. Test in isolation (like Phase 1) with 20 backtests
3. Find optimal weight multiplier
4. Compare Sharpe ratio to Phase 2 winner (0.310 baseline)

### Phase 3B: Integration Testing
1. Test adding top Phase 3 performer to current 3-indicator config
2. Test replacing weakest current indicator with Phase 3 performer
3. Run combination tests like Phase 2

### Success Criteria
- **Add to production if:** New indicator + existing config > 0.340 Sharpe (+10% improvement)
- **Replace existing if:** Swap improves Sharpe by >5%
- **Reject if:** No improvement or degrades performance

## Priority Queue

**Immediate (Next 1-2 weeks):**
1. ✅ Relative Strength vs SPY - In development
2. Gap Analysis - High impact, simple to implement

**Short-term (2-4 weeks):**
3. VWAP - Institutional confirmation
4. TTM Squeeze - Volatility compression

**Medium-term (1-2 months):**
5. Aroon - Alternative trend detection
6. Keltner Channels - Required for TTM Squeeze

**Low Priority (Future):**
7. Elder's Force Index - May overlap with volume indicators
8. A/D Line - May be redundant with OBV/CMF

## Expected Outcomes

**Best Case:**
- RS vs SPY adds significant value → 0.350+ Sharpe
- Gap Analysis captures breakouts we're missing → 0.380+ Sharpe
- New optimal config: 4-5 indicators with >0.400 Sharpe

**Realistic Case:**
- 1-2 new indicators improve performance by 5-15%
- Final Sharpe: 0.320-0.340
- Keep 3-indicator simplicity or expand to 4

**Worst Case:**
- New indicators don't improve isolated performance
- Current 3-indicator config remains optimal
- No changes to production

## Implementation Notes

### Data Requirements
- **RS vs SPY:** Need SPY data in database (already have)
- **Gap Analysis:** Uses existing OHLC data
- **VWAP:** May need intraday data or use approximation
- **Others:** Can use existing daily OHLC data

### Code Changes
1. Add indicator calculations to appropriate files:
   - RS → `momentum_indicators.py` or new `relative_strength_indicators.py`
   - Gap → `price_action_indicators.py` (new file)
   - VWAP → `volume_indicators.py`
   - TTM/Keltner → `trend_indicators.py` or `volatility_indicators.py`

2. Add weights to `weights.json`
3. Update `technical_analyzer.py` to call new indicators
4. Write tests for each indicator

### Testing Framework
- Use existing Phase 1 test harness
- 20 backtests per configuration
- Random date selection
- Same hold period (5 days)
- Same position sizing

## References

- **Relative Strength:** IBD Methodology, Mark Minervini's "Trade Like a Stock Market Wizard"
- **TTM Squeeze:** John Carter's "Mastering the Trade"
- **Elder's Force Index:** Alexander Elder's "Trading for a Living"
- **Gap Analysis:** Mark Minervini's SEPA (Specific Entry Point Analysis)
- **VWAP:** Institutional trading standard

## Next Actions

1. ✅ Create this planning document
2. ⏳ Implement Relative Strength vs SPY
3. ⏳ Test RS in isolation (Phase 3A)
4. ⏳ Compare to Phase 2 baseline
5. ⏳ Decide: add, replace, or reject
6. ⏳ Move to next indicator (Gap Analysis)

---

**Created:** 2026-01-30
**Status:** Planning phase - starting with RS vs SPY implementation
