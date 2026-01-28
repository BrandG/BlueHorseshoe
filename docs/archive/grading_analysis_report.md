# Grading Engine Analysis Report - Dec 2025

## Executive Summary
The Grading Engine was used to evaluate the `mean_reversion` strategy for the period of 2025-12-15 to 2025-12-19. The analysis revealed that stocks with extreme negative technical scores (indicating significant oversold or bearish conditions) exhibited high win rates when evaluated with a trend-following entry delay.

## Key Findings

### 1. Performance by Score Tier
- **Extreme Negative Scores (-5 to -9):** High win rates (70% - 100%). These stocks were often significantly below their moving averages or at local lows.
- **Extreme Positive Scores (18+):** Also high win rates (66% - 100%), but with very low sample sizes.
- **Neutral Scores (0 to 10):** Mediocre win rates (30% - 45%) and slightly negative average PnL.

### 2. Component Analysis
- **Moving Average:** Trades where price was BELOW the 20-day WMA/VWMA (`is_bullish=False`) had a **75.78% win rate** and **2.04% avg PnL**.
- **RSI Penalty:** The RSI overbought penalty (`penalty_rsi`) was highly effective at filtering out bad trades, with only a **9.62% win rate** for stocks triggering this penalty.
- **Trend:** Bearish trend signals (`trend=False`) performed better than bullish ones (**53.93% vs 42.23%**), suggesting that "buying the dip" in a downtrend (with a 5% further discount) is a viable mean-reversion tactic.

## Recommendations for Strategy Refinement

1. **Formalize Mean Reversion:** Explicitly reward oversold conditions (RSI < 30, BB < 0.1) in the `TechnicalAnalyzer` to identify these high-probability bounce candidates more effectively.
2. **Optimize Entry Timing:** The current 5% discount for "Strong Downtrend" seems to work well. We should test if varying this discount based on volatility (ATR) improves results.
3. **Filter Overbought:** Maintain the RSI penalty as it is a strong "Don't Buy" signal for both trend and mean-reversion strategies.
4. **Volume Exhaustion:** The `penalty_volume_exhaustion` also showed a low win rate (33.75%), confirming that buying into a massive volume spike (likely a "blow-off top") is risky.

## Next Steps
- Implement "Oversold Bonus" in `TechnicalAnalyzer`.
- Run a comparative backtest between `baseline` (trend-following) and a refined `mean_reversion` strategy over a longer period (e.g., 6 months).
