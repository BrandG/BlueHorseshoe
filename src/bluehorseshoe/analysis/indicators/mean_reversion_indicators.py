"""
mean_reversion_indicators.py

Dedicated mean-reversion indicators that detect oversold/reversal conditions.
Unlike the baseline trend-following indicators reused with mr_ weight prefixes,
these are purpose-built for mean-reversion scoring.

Sub-indicators:
    - RSI Divergence: Bullish price/RSI divergence detection
    - Z-Score: Statistical distance from moving average
    - Connors RSI: Composite short-term reversal oscillator
    - DV2: David Varadi's bounded oscillator
    - Short-Period ROC: 2-day rate of change for sharp drops
"""

from typing import Optional

import numpy as np
import pandas as pd
import talib as ta

from bluehorseshoe.analysis.indicators.indicator import Indicator, IndicatorScore
from bluehorseshoe.core.config import weights_config


class MeanReversionIndicator(Indicator):
    """
    Calculates dedicated mean-reversion indicators for detecting
    oversold conditions and potential reversal setups.
    """

    def __init__(self, data: pd.DataFrame, weight_category: str = None):
        self.weights = weights_config.get_weights(weight_category or 'mean_reversion_specific')
        self.required_cols = ['close', 'high', 'low']
        super().__init__(data)

    def calculate_rsi_divergence(self, lookback: int = 14) -> float:
        """
        Detect bullish RSI divergence: price makes lower low but RSI makes higher low.

        Uses a 5-bar swing-low detection window over the last `lookback` bars.

        Returns:
            float: +3.0 clear divergence, +1.5 weak, 0.0 none
        """
        if 'rsi_14' not in self.days.columns or len(self.days) < 20:
            return 0.0

        close = self.days['close'].values
        rsi = self.days['rsi_14'].values

        if np.any(np.isnan(rsi[-lookback:])):
            return 0.0

        # Find swing lows in the last `lookback` bars using 5-bar window
        swing_lows = []
        start = max(2, len(close) - lookback)
        for i in range(start, len(close) - 2):
            if close[i] <= close[i - 1] and close[i] <= close[i - 2] and \
               close[i] <= close[i + 1] and close[i] <= close[i + 2]:
                swing_lows.append(i)

        if len(swing_lows) < 2:
            return 0.0

        # Compare two most recent swing lows
        prev_idx = swing_lows[-2]
        curr_idx = swing_lows[-1]

        price_lower = close[curr_idx] < close[prev_idx]
        rsi_higher = rsi[curr_idx] > rsi[prev_idx]

        if price_lower and rsi_higher:
            rsi_diff = rsi[curr_idx] - rsi[prev_idx]
            if rsi_diff > 5:
                return 3.0  # Clear divergence
            return 1.5  # Weak divergence

        return 0.0

    def calculate_zscore(self) -> float:
        """
        Z-Score: (close - EMA20) / std_20

        Measures how many standard deviations price is from its mean.

        Returns:
            float: +3.0 if Z < -2.5, +2.0 if < -2.0, +1.0 if < -1.5, -1.0 if > 2.0
        """
        if len(self.days) < 20:
            return 0.0

        close = self.days['close'].iloc[-1]

        # Use enriched columns or compute inline
        if 'ema_20' in self.days.columns and 'std_20' in self.days.columns:
            ema = self.days['ema_20'].iloc[-1]
            std = self.days['std_20'].iloc[-1]
        else:
            ema = self.days['close'].ewm(span=20, adjust=False).mean().iloc[-1]
            std = self.days['close'].rolling(20).std().iloc[-1]

        if pd.isna(std) or std == 0 or pd.isna(ema):
            return 0.0

        z = (close - ema) / std

        if z < -2.5:
            return 3.0
        elif z < -2.0:
            return 2.0
        elif z < -1.5:
            return 1.0
        elif z > 2.0:
            return -1.0
        return 0.0

    def calculate_connors_rsi(self) -> float:
        """
        Connors RSI: average of three components (0-100 scale):
          1. RSI(3) of close
          2. RSI(2) of up/down streak length
          3. Percentile rank of ROC(2) over last 100 bars

        Returns:
            float: +3.0 if CRSI < 10, +2.0 if < 20, +1.0 if < 30, -1.0 if > 80
        """
        if len(self.days) < 30:
            return 0.0

        close = self.days['close'].values

        # Component 1: RSI(3)
        if 'rsi_3' in self.days.columns:
            rsi3 = self.days['rsi_3'].iloc[-1]
        else:
            rsi3_series = ta.RSI(self.days['close'], timeperiod=3)  # type: ignore
            rsi3 = rsi3_series.iloc[-1]

        if pd.isna(rsi3):
            return 0.0

        # Component 2: Streak RSI(2)
        # Calculate consecutive up/down streak
        streaks = np.zeros(len(close))
        for i in range(1, len(close)):
            if close[i] > close[i - 1]:
                streaks[i] = streaks[i - 1] + 1 if streaks[i - 1] > 0 else 1
            elif close[i] < close[i - 1]:
                streaks[i] = streaks[i - 1] - 1 if streaks[i - 1] < 0 else -1
            else:
                streaks[i] = 0

        streak_series = pd.Series(streaks)
        streak_rsi = ta.RSI(streak_series, timeperiod=2)  # type: ignore
        streak_rsi_val = streak_rsi.iloc[-1]
        if pd.isna(streak_rsi_val):
            return 0.0

        # Component 3: Percentile rank of ROC(2)
        if 'roc_2' in self.days.columns:
            roc2 = self.days['roc_2'].values
        else:
            roc2 = ta.ROC(self.days['close'], timeperiod=2).values  # type: ignore

        lookback = min(100, len(roc2))
        roc2_window = roc2[-lookback:]
        current_roc2 = roc2[-1]

        if pd.isna(current_roc2):
            return 0.0

        valid_roc2 = roc2_window[~np.isnan(roc2_window)]
        if len(valid_roc2) == 0:
            return 0.0

        pct_rank = (np.sum(valid_roc2 < current_roc2) / len(valid_roc2)) * 100

        # CRSI = mean of three components
        crsi = (rsi3 + streak_rsi_val + pct_rank) / 3.0

        if crsi < 10:
            return 3.0
        elif crsi < 20:
            return 2.0
        elif crsi < 30:
            return 1.0
        elif crsi > 80:
            return -1.0
        return 0.0

    def calculate_dv2(self) -> float:
        """
        DV2 oscillator: 2-day rolling mean of (close - low) / (high - low).

        Bounded 0-1 oscillator; low values indicate selling exhaustion.

        Returns:
            float: +3.0 if < 0.1, +2.0 if < 0.2, +1.0 if < 0.3, -1.0 if > 0.8
        """
        if len(self.days) < 3:
            return 0.0

        if 'dv2' in self.days.columns:
            dv2_val = self.days['dv2'].iloc[-1]
        else:
            high = self.days['high']
            low = self.days['low']
            close = self.days['close']
            hl_range = high - low
            hl_range = hl_range.replace(0, np.nan)
            dv2_val = ((close - low) / hl_range).rolling(2).mean().iloc[-1]

        if pd.isna(dv2_val):
            return 0.0

        if dv2_val < 0.1:
            return 3.0
        elif dv2_val < 0.2:
            return 2.0
        elif dv2_val < 0.3:
            return 1.0
        elif dv2_val > 0.8:
            return -1.0
        return 0.0

    def calculate_short_roc(self) -> float:
        """
        Short-period Rate of Change using ROC(2) and ROC(5).

        Detects sharp short-term drops that may indicate oversold bounce opportunities.

        Returns:
            float: +3.0 if ROC_2 < -5%, +2.0 if < -3%, +1.0 if < -2%,
                   bonus +1.0 if ROC_5 also < -5%, -1.0 if ROC_2 > 5%
        """
        if len(self.days) < 6:
            return 0.0

        if 'roc_2' in self.days.columns:
            roc2 = self.days['roc_2'].iloc[-1]
        else:
            roc2_series = ta.ROC(self.days['close'], timeperiod=2)  # type: ignore
            roc2 = roc2_series.iloc[-1]

        if pd.isna(roc2):
            return 0.0

        score = 0.0

        if roc2 < -5.0:
            score = 3.0
        elif roc2 < -3.0:
            score = 2.0
        elif roc2 < -2.0:
            score = 1.0
        elif roc2 > 5.0:
            return -1.0

        # Bonus if ROC(5) also deeply negative
        if score > 0 and 'roc_5' in self.days.columns:
            roc5 = self.days['roc_5'].iloc[-1]
            if not pd.isna(roc5) and roc5 < -5.0:
                score += 1.0

        return score

    def calculate_falling_knife(self) -> float:
        """
        Detect two consecutive red candles ending on the most recent bar.

        Returns:
            float: -5.0 when the last two candles both close below open, else 0.0
        """
        if len(self.days) < 2 or 'open' not in self.days.columns or 'close' not in self.days.columns:
            return 0.0

        recent = self.days[['open', 'close']].tail(2)
        if recent.isna().any().any():
            return 0.0

        both_red = (recent['close'] < recent['open']).all()
        return -5.0 if both_red else 0.0

    def get_score(self, enabled_sub_indicators: Optional[list[str]] = None, aggregation: str = "sum") -> IndicatorScore:
        """
        Compute aggregate buy/sell scores from all mean-reversion sub-indicators.

        Args:
            enabled_sub_indicators: List of sub-indicators to enable (default: all)
            aggregation: How to combine scores - "sum" or "product" (default: sum)

        Returns:
            IndicatorScore: Named tuple with buy_score and sell_score
        """
        buy_score = 1.0 if aggregation == "product" else 0.0
        active_count = 0

        sub_map = {
            'rsi_divergence': (self.calculate_rsi_divergence, 'RSI_DIVERGENCE_MULTIPLIER'),
            'zscore': (self.calculate_zscore, 'ZSCORE_MULTIPLIER'),
            'connors_rsi': (self.calculate_connors_rsi, 'CONNORS_RSI_MULTIPLIER'),
            'dv2': (self.calculate_dv2, 'DV2_MULTIPLIER'),
            'short_roc': (self.calculate_short_roc, 'SHORT_ROC_MULTIPLIER'),
        }

        for name, (func, weight_key) in sub_map.items():
            if enabled_sub_indicators is None or name in enabled_sub_indicators:
                multiplier = self.weights[weight_key] if weight_key else 1.0
                if multiplier == 0.0:
                    continue
                score = func() * multiplier  # pylint: disable=not-callable
                if aggregation == "product":
                    buy_score *= score
                else:
                    buy_score += score
                active_count += 1

        # Cap mr_specific contribution to prevent score dominance
        if aggregation == "sum" and buy_score > 8.0:
            buy_score = 8.0

        if active_count == 0 or (aggregation == "product" and buy_score == 0):
            buy_score = 0.0

        sell_score = 0.0
        return IndicatorScore(buy_score, sell_score)

    def graph(self):
        """Reserved for visualizing mean reversion indicators."""
        pass
