# Position Sizer - Quick Start Guide

## Understanding Risk Percentages

**Two key concepts:**

1. **Account Risk %** - How much of your TOTAL capital you risk on this trade
   - Example: 1% of $2000 = $20 maximum loss

2. **Position Risk %** - How much the stock can drop from entry to stop
   - Example: Entry $100, Stop $95 = 5% position risk

**Position sizing connects them:**

```
Account Risk ($) = Account Size × Account Risk %
Risk per Share = Entry Price - Stop Price
Shares to Buy = Account Risk ($) / Risk per Share
```

**Example:**
- Account: $2,000
- Account risk: 1% = $20
- Entry: $100, Stop: $95
- Risk per share: $5
- **Shares: $20 ÷ $5 = 4 shares**

If stopped out: 4 shares × $5 loss = **$20 total** (exactly 1% of account) ✅

---

## Three Tools Available

### 1. Enhanced Calculator (RECOMMENDED)

**Auto-calculates entry/stop/target using BlueHorseshoe's ATR methodology**

```bash
# Baseline (Trend) strategy
docker exec bluehorseshoe python position_sizer_enhanced.py \
  --account 2000 --risk 1.0 --symbol GEF --strategy baseline

# Mean Reversion strategy
docker exec bluehorseshoe python position_sizer_enhanced.py \
  --account 2000 --risk 1.0 --symbol AAPL --strategy mean_reversion
```

**When to use:**
- ✅ You want BlueHorseshoe to calculate optimal stops/targets
- ✅ You're exploring new trades not in the daily report
- ✅ You want ATR-based, volatility-adjusted levels

### 2. Quick Sizer

**Paste signals directly from BlueHorseshoe reports**

```bash
python quick_size.py
> GEF - Entry: 75.34 | Stop: 70.43 | Target: 80.45
> BUY 4.073 SHARES
```

**When to use:**
- ✅ You're trading from the daily BlueHorseshoe report
- ✅ You want the fastest calculation
- ✅ You trust the pre-calculated levels

### 3. Standard Calculator

**Manual entry of all prices**

```bash
python position_sizer.py \
  --account 2000 --risk 1.0 \
  --entry 75.34 --stop 70.43 --target 80.45
```

**When to use:**
- ✅ You have custom entry/stop/target levels
- ✅ You're outside Docker environment
- ✅ You don't need auto-calculation

---

## How BlueHorseshoe Calculates Stops & Targets

### Baseline (Trend) Strategy

**Entry:** Close - (0.20 × ATR)
- Slight pullback from current price
- Discount adjusts based on signal strength

**Stop Loss:** Entry - (2.0 × ATR) OR swing_low_5 × 0.985
- Whichever is safer (wider)
- Adapts to volatility

**Target:** Max of (20-day high, Entry + 3.0 × ATR)
- Conservative profit target
- Based on recent resistance

### Mean Reversion Strategy

**Entry:** Current close
- Buy the dip immediately

**Stop Loss:** Entry - (1.5 × ATR)
- Tighter stop for quick reversals

**Target:** Max of (20-day EMA, Entry + 2.0 × ATR)
- Reversion to mean

---

## Usage Examples

### Example 1: New Trade Exploration

**You like AAPL but it's not in today's report. What should you buy?**

```bash
docker exec bluehorseshoe python position_sizer_enhanced.py \
  --account 2000 --risk 1.0 --symbol AAPL --strategy baseline
```

Output tells you:
- Entry: $276.49
- Stop: $267.40
- Target: $288.60
- **Buy 2.201 shares**

### Example 2: Daily Report Trade

**BlueHorseshoe report shows: GEF - Entry: 75.34 | Stop: 70.43 | Target: 80.45**

```bash
python quick_size.py
# Paste: GEF - Entry: 75.34 | Stop: 70.43 | Target: 80.45
# Output: BUY 4.073 SHARES
```

### Example 3: Custom Levels

**You want tighter stops than BlueHorseshoe's defaults**

```bash
python position_sizer.py \
  --account 2000 --risk 0.5 \
  --entry 75.34 --stop 73.00 --target 80.45
```

---

## Risk Management Guidelines

### For $2,000 - $10,000 Accounts

**During Validation Phase (First 20-30 trades):**
- Risk: **0.5-1.0%** per trade
- Max positions: **5 concurrent**
- Max total risk: **5%** of portfolio

**After Validation (Proven system):**
- Risk: **1.0-2.0%** per trade
- Max positions: **5-8 concurrent**
- Max total risk: **10%** of portfolio

### Expected Returns (Conservative)

**With Sharpe 1.0 and proper risk management:**
- Annual: **10-15%** (beating S&P 500)
- Monthly: **0.5-1.5%** average
- Per trade: **1-3%** on winners, -0.5-1% on losers
- Win rate: **50-60%**

**Your +2% overnight trade was excellent but not typical!**

---

## Strategy Selection Guide

### Use Baseline (Trend) When:
- ✅ Stock is in an uptrend
- ✅ Momentum is strong
- ✅ Breaking out of consolidation
- ✅ Market regime is Bullish/Neutral

### Use Mean Reversion When:
- ✅ Stock is oversold (RSI <30)
- ✅ Sharp pullback in quality name
- ✅ Price below lower Bollinger Band
- ✅ High-quality name having a bad day

---

## Troubleshooting

**"Cannot import BlueHorseshoe modules"**
- You're outside Docker. Use manual mode or run inside Docker:
  ```bash
  docker exec bluehorseshoe python position_sizer_enhanced.py ...
  ```

**"No historical data found for symbol"**
- Symbol not in database. Run update first:
  ```bash
  docker exec bluehorseshoe python src/main.py -u
  ```

**"R/R ratio below 1:1"**
- Risk/reward is unfavorable
- Consider wider target or tighter stop
- Or skip this trade

**"Total risk exceeds 10%"**
- You have too many open positions
- Close some positions before adding new ones
- Or reduce risk % per trade

---

## Next Steps

1. **Start small:** Use 0.5-1% risk for first 10 trades
2. **Track everything:** Use `position_tracker.csv`
3. **Build sample:** Need 20-30 trades to validate system
4. **Compare:** Your live results vs backtest Sharpe ~1.0
5. **Scale up:** Increase risk % as confidence builds

**Remember:** Position sizing is the difference between winning and surviving!
