# Position Sizing Guide for BlueHorseshoe

## Quick Start

You have three tools to manage position sizing:

1. **Enhanced Calculator** (`position_sizer_enhanced.py`) - **NEW!** Auto-calculates stops/targets from BlueHorseshoe logic
2. **Standard Calculator** (`position_sizer.py`) - Manual entry of prices
3. **Quick Sizer** (`quick_size.py`) - Paste-and-go from BlueHorseshoe reports
4. **Spreadsheet Tracker** (`position_tracker.csv`) - Track all positions

---

## Tool 1: Enhanced Position Sizing Calculator (NEW!)

### Auto-Calculation Mode

**The enhanced calculator can automatically calculate entry, stop-loss, and target prices using BlueHorseshoe's proven ATR-based methodology.**

```bash
# Auto mode - Baseline (Trend) strategy
docker exec bluehorseshoe python position_sizer_enhanced.py \
  --account 2000 \
  --risk 1.0 \
  --symbol GEF \
  --strategy baseline

# Auto mode - Mean Reversion strategy
docker exec bluehorseshoe python position_sizer_enhanced.py \
  --account 2000 \
  --risk 1.0 \
  --symbol AAPL \
  --strategy mean_reversion
```

**Example Output:**
```
🔄 Calculating levels for GEF using baseline strategy...

✅ Auto-calculated levels:
   Entry:  $75.04
   Stop:   $67.57
   Target: $81.05

POSITION SIZE CALCULATOR - GEF
Strategy: Baseline (Trend)
═══════════════════════════════════════

📊 ACCOUNT INFO:
   Total Capital:        $2,000.00
   Risk per Trade:       1.0%
   Max Risk ($):         $20.00

📈 MARKET DATA:
   Current Close:        $75.44
   ATR (14-day):         $2.00

💰 TRADE DETAILS:
   Entry Price:          $75.04 (0.53% below close)
   Stop Loss:            $67.57
   Target Price:         $81.05

✅ POSITION SIZE: BUY 2.678 SHARES @ $75.04
```

### Manual Mode (Still Available)

```bash
# Manual entry (works outside Docker)
python position_sizer_enhanced.py \
  --account 2000 \
  --risk 1.0 \
  --entry 75.34 \
  --stop 70.43 \
  --target 80.45

# Interactive mode
docker exec bluehorseshoe python position_sizer_enhanced.py --interactive
```

---

## Tool 2: Standard Position Sizing Calculator

### Basic Usage

```bash
# Interactive mode (easiest)
python position_sizer.py --interactive

# Quick calculation
python position_sizer.py --account 2000 --risk 1.0 --entry 75.34 --stop 70.43 --target 80.45
```

### Real-World Example (Your Current Account)

**Scenario: GEF trade from Feb 5 prediction**

```bash
python position_sizer.py \
  --account 2000 \
  --risk 1.0 \
  --entry 75.34 \
  --stop 70.43 \
  --target 80.45 \
  --symbol GEF
```

**Result:**
- **Buy:** 4 shares @ $75.34
- **Cost:** $301.36 (15% of capital)
- **Risk:** $19.64 if stopped (0.98%)
- **Potential:** $20.44 gain if target hit (1.02%)

### With Multiple Positions Open

If you already have 2 positions open risking $15 each:

```bash
python position_sizer.py \
  --account 2000 \
  --risk 1.0 \
  --entry 75.34 \
  --stop 70.43 \
  --open-risk 30
```

Calculator will show:
- This trade risk: $19.64
- Other positions: $30.00
- **Total risk: $49.64 (2.48%)**

---

## Tool 2: Position Tracker Spreadsheet

### Setup

1. Open `position_tracker.csv` in Excel/Google Sheets
2. Update **Account Size** in cell B1 (currently $2,000)
3. Set **Risk Per Trade %** in cell D1 (recommend 1.0%)

### For Each Trade

Fill in these columns:
- **Date:** Trade entry date
- **Symbol:** Stock ticker
- **Entry:** Entry price
- **Stop:** Stop loss price
- **Target:** Target price
- **Status:** OPEN, CLOSED, WIN, LOSS

The spreadsheet calculates:
- Shares to buy
- Position cost
- Risk amount
- Potential gain
- R/R ratio

### Example Row (Current GEF Trade)

| Date | Symbol | Entry | Stop | Target | Shares | Cost | Risk $ | Risk % | Status |
|------|--------|-------|------|--------|--------|------|--------|--------|--------|
| 2/5/26 | GEF | 75.34 | 70.43 | 80.45 | 4 | 301.36 | 19.64 | 0.98% | OPEN |

When trade closes:
- Update **Status** to WIN or LOSS
- Fill in **Exit Price**
- Calculate **Actual P/L**

---

## Position Sizing Rules (Your Account)

### Current Account: $2,000

**Conservative (Recommended for first 20 trades):**
- Risk: **0.5-1% per trade** = $10-20
- Max positions: **3-5**
- Total risk: **2.5-5%** = $50-100

**Example Portfolio:**
```
Position 1: 4 shares GEF   - Risk: $19.64
Position 2: 8 shares XYZ   - Risk: $18.00
Position 3: 12 shares ABC  - Risk: $15.00
Total Risk: $52.64 (2.63% of account) ✓
```

### At $5,000 (After Adding Capital)

**Risk: 1% per trade** = $50
- Typical position: $750-1,000
- Max 5 positions: $250 total risk (5%)

**Example:**
- GEF: 10 shares @ $75.34 = $753 position, $49 risk

### At $10,000 (Growth Phase)

**Risk: 1-1.5% per trade** = $100-150
- Typical position: $1,500-2,000
- Max 5 positions: $500-750 total risk (5-7.5%)

**Example:**
- GEF: 20 shares @ $75.34 = $1,507 position, $98 risk

---

## Workflow: Taking a Trade

### Step 1: Get BlueHorseshoe Signal

From daily report:
```
GEF - Entry: 75.34 | Stop: 70.43 | Target: 80.45 | Score: 38.25 | ML: 60.7%
```

### Step 2: Calculate Position Size

```bash
python position_sizer.py --account 2000 --risk 1.0 --entry 75.34 --stop 70.43 --target 80.45
```

Output: **Buy 4 shares @ $75.34**

### Step 3: Check Total Exposure

Look at open positions:
- Position 1: $15 risk
- Position 2: $18 risk
- This trade: $19.64 risk
- **Total: $52.64 (2.63%)** ✓ Under 5% limit

### Step 4: Execute Trade

- Buy 4 shares GEF @ $75.34
- Set stop loss @ $70.43
- Set target (optional) @ $80.45

### Step 5: Track in Spreadsheet

Add row to `position_tracker.csv`:
```
2026-02-05, GEF, 75.34, 70.43, 80.45, 4.91, 4, 301.36, 19.64, 0.98%, 20.44, 1.02%, 1.04, OPEN
```

---

## Maximum Risk Limits

**Never exceed these:**

| Account | Risk/Trade | Max Positions | Total Risk | Max Loss |
|---------|------------|---------------|------------|----------|
| $2,000 | 1% ($20) | 5 | 5% ($100) | -5% |
| $5,000 | 1% ($50) | 5 | 5% ($250) | -5% |
| $10,000 | 1% ($100) | 5 | 5% ($500) | -5% |

**Why 5% total risk?**
- If all 5 positions stop out same day: -5% drawdown
- Painful but survivable
- Can recover with 2-3 good trades

---

## Position Sizing Examples by Stock Price

All examples with $2,000 account, 1% risk:

### Cheap Stock ($10-20)

```
Entry: $15.00
Stop: $14.00
Risk per share: $1.00

Calculation: $20 / $1.00 = 20 shares
Position: 20 × $15 = $300 (15% of capital) ✓
```

### Mid-Price Stock ($50-100)

```
Entry: $75.34
Stop: $70.43
Risk per share: $4.91

Calculation: $20 / $4.91 = 4 shares
Position: 4 × $75.34 = $301 (15% of capital) ✓
```

### Expensive Stock ($200-300)

```
Entry: $250.00
Stop: $240.00
Risk per share: $10.00

Calculation: $20 / $10.00 = 2 shares
Position: 2 × $250 = $500 (25% of capital) ✓
```

**Key insight:** Risk stays at $20 (1%), but position size adjusts!

---

## What If Calculator Says 0 Shares?

**Example:**
```
Account: $2,000
Risk: 1% = $20
Entry: $300
Stop: $270
Risk per share: $30

Calculation: $20 / $30 = 0.66 shares → 0 shares
```

**Options:**
1. **Skip the trade** (safest - stop too wide)
2. Increase account size
3. Reduce risk tolerance (not recommended)
4. Use tighter stop (risky - may get stopped out more)

**Recommendation:** Skip it. This is risk management working correctly.

---

## Red Flags to Watch For

### ⚠️ Warning Signs

**1. Position too large (>30% of capital)**
- Indicates stop is too tight or account too small
- Risk: One bad trade = big drawdown

**2. Total risk >10%**
- Too much exposure across portfolio
- Close a position or skip new trade

**3. R/R ratio <0.8:1**
- Not enough upside for the risk
- Skip or find better entry

**4. Can't afford minimum position (1 share)**
- Account too small for this stock
- Trade cheaper stocks or add capital

---

## As Your Account Grows

### $2,000 → $3,000 (50% gain)

Update calculator:
```bash
python position_sizer.py --account 3000 --risk 1.0
```

New position sizes:
- Risk per trade: $30 (vs $20)
- GEF example: 6 shares (vs 4 shares)
- Position cost: $452 (vs $301)

**Same 1% risk, larger absolute dollars**

### $3,000 → $5,000

- Risk per trade: $50
- GEF: 10 shares
- Can handle wider stops
- More diverse positions

### $5,000 → $10,000

- Risk per trade: $100
- GEF: 20 shares
- Can trade higher-priced stocks
- More opportunities

**Key:** Update `--account` parameter as capital grows!

---

## Common Mistakes to Avoid

### ❌ DON'T:

1. **"This looks good, I'll buy 10 shares"**
   - Ignores stop loss distance
   - May risk 5% or 0.1% randomly

2. **"I'll risk 5% since I'm confident"**
   - One bad trade = 5% loss
   - 3 bad trades = -15%

3. **"Stock fell, I'll buy more to average down"**
   - Increases risk instead of cutting it
   - Violates stop loss discipline

4. **"I'll skip the stop loss this time"**
   - No position sizing can save you
   - One big loss wipes out 10 wins

### ✅ DO:

1. **Calculate every position**
   - Use the calculator
   - Respect the output

2. **Honor stop losses**
   - Set them when you enter
   - Don't move them (except trailing up)

3. **Track total exposure**
   - Check before adding positions
   - Stay under 5-10% total risk

4. **Update account size**
   - Recalculate as capital grows
   - Take profits/losses into account

---

## Quick Reference Card

```
┌─────────────────────────────────────────┐
│   BLUEHORSESHOE POSITION SIZING RULES   │
├─────────────────────────────────────────┤
│ Account: $______ (update regularly)     │
│ Risk per Trade: 1%                      │
│ Max Positions: 5                        │
│ Max Total Risk: 5%                      │
├─────────────────────────────────────────┤
│ FORMULA:                                │
│ Shares = (Account × Risk%) / (Entry - Stop)│
│                                         │
│ EXAMPLE (GEF):                          │
│ ($2,000 × 1%) / ($75.34 - $70.43)     │
│ = $20 / $4.91 = 4 shares               │
├─────────────────────────────────────────┤
│ CHECKLIST BEFORE EVERY TRADE:           │
│ ☐ Calculated position size              │
│ ☐ Total risk <5% with all positions     │
│ ☐ R/R ratio >1:1                        │
│ ☐ Stop loss order placed                │
│ ☐ Trade logged in spreadsheet           │
└─────────────────────────────────────────┘
```

---

## Support & Questions

**Calculator location:** `/root/BlueHorseshoe/position_sizer.py`
**Tracker location:** `/root/BlueHorseshoe/position_tracker.csv`

**Usage:**
```bash
# Interactive mode
python position_sizer.py --interactive

# Quick calc
python position_sizer.py --account [SIZE] --risk [%] --entry [PRICE] --stop [PRICE]

# Help
python position_sizer.py --help
```

---

## Remember

**Position sizing is more important than entry timing.**

- Good entries + bad sizing = Bankruptcy
- Average entries + good sizing = Profitability

**Your edge:** BlueHorseshoe finds good setups
**Your job:** Size them correctly and stick to the plan

**Goal:** Survive long enough to let the system work!
