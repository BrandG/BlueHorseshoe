# Implemented Technical Indicators

This document lists all technical indicators currently implemented in the BlueHorseshoe codebase, categorized by their type.

## 1. Momentum Indicators
*File: `src/bluehorseshoe/analysis/indicators/momentum_indicators.py`*

*   **RSI (Relative Strength Index):** Checks if the 14-day RSI is below 50 (score 2) or below 60 (score 1).
*   **ROC (Rate of Change):** 5-day Rate of Change. Scores based on standard deviation comparison ( > 2*std or > 1*std).
*   **MACD (Moving Average Convergence Divergence):** Scores if MACD line > Signal line, with higher scores for larger differences.
*   **Bollinger Band Position:** Calculates price position relative to bands. Scores for specific zones (0.3-0.7, 0.1-0.3, or >0.85).
*   **Williams %R:** Momentum indicator measuring overbought/oversold levels. Scores for Oversold (<-80) and penalizes Overbought (>-20).
*   **CCI (Commodity Channel Index):** Measures current price relative to average price. Scores for Extreme Oversold (<-200) and Oversold (<-100).

## 2. Trend Indicators
*File: `src/bluehorseshoe/analysis/indicators/trend_indicators.py`*

*   **Stochastic Oscillator:** Detects crossovers (K vs D) and overbought/oversold conditions (<20 / >80).
*   **Ichimoku Cloud:** Complex scoring based on Price vs Cloud, Tenkan/Kijun cross, and Cloud color (Span A vs B).
*   **Parabolic SAR (PSAR):** Detects trend flips (SAR moving from above to below price, or vice-versa).
*   **Heiken Ashi:** Scores consecutive bullish candles based on Heiken Ashi transformed prices.
*   **ADX / DMI:** Average Directional Index. Scores strong trends (ADX > 25, 30, 35) if DMI+ > DMI-.
*   **Donchian Channels:** Checks for breakouts (Close > Upper Band) or breakdowns (Close < Lower Band) using shifted bands.
*   **SuperTrend:** ATR-based trailing stop indicator. Scores trend direction and crossovers (flips).

## 3. Volume Indicators
*File: `src/bluehorseshoe/analysis/indicators/volume_indicators.py`*

*   **OBV (On-Balance Volume):** Scores based on the trend (slope) of OBV over a 5-day window.
*   **CMF (Chaikin Money Flow):** Measures buying/selling pressure. Scores if CMF > 0.05 or > 0.
*   **ATR Band:** Compares price to MA +/- ATR multiplier. Checks for overextension or oversold conditions.
*   **ATR Spike:** Detects volatility spikes (Current ATR >= 1.5x Past ATR).
*   **MFI (Money Flow Index):** Volume-weighted RSI. Scores for Oversold (<20, <30) and Overbought (>80).
*   **Average Volume:** Simple filter checking if average volume is sufficient (> 100k).

## 4. Moving Average Indicators
*File: `src/bluehorseshoe/analysis/indicators/moving_average_indicators.py`*

*   **WMA (Weighted Moving Average):** Checks if Close > 20-day WMA.
*   **VWMA (Volume-Weighted Moving Average):** Checks if Close > 20-day VWMA.
*   **EMA Crossover:** Checks for "Perfect Bullish Alignment": EMA(9) > EMA(21) > EMA(Slow - avg of 50/200).

## 5. Candlestick Patterns
*File: `src/bluehorseshoe/analysis/indicators/candlestick_indicators.py`*

*   **Three White Soldiers:** Bullish reversal pattern with 3 consecutive white candles.
*   **Rising/Falling Three Methods:** Continuation patterns detected via TA-Lib.
*   **Marubozu:** Strong trend candle (no shadows) detected via TA-Lib.
*   **Belt Hold:** Reversal pattern detected via TA-Lib.

## 6. Limit / Pivot Indicators
*File: `src/bluehorseshoe/analysis/indicators/limit_indicators.py`*

*   **Pivot Points:** Calculates Classic Pivot Points (P, R1, R2, S1, S2). Scores based on price position relative to these levels (e.g., breakout above R1/R2, bounce off Pivot).
*   **52-Week Range:** Checks if price is near the 52-week high (>90% of range) or low (<10% of range).
