import numpy as np
import pandas as pd

from indicators.indicator import Indicator, IndicatorScore

RSI_MULTIPLIER = 1.0
ROC_MULTIPLIER = 1.0
MACD_MULTIPLIER = 1.0
MACD_SIGNAL_MULTIPLIER = 0.15
BB_MULTIPLIER = 1.0

class MomentumIndicator(Indicator):

    def __init__(self, data: pd.DataFrame):
        self.required_cols = ['close', 'high', 'low']
        super().__init__(data)

    def calculate_rsi(self) -> float:
        yesterday = self.days.iloc[-1]
        if 'rsi_14' in yesterday:
            return np.select(
                [
                    (yesterday['rsi_14'] >= 45) & (yesterday['rsi_14'] <= 65),
                    (yesterday['rsi_14'] >= 40) & (yesterday['rsi_14'] <= 70)
                ],
                [2, 1],
                0
            ).item()
        return 0

    def calculate_roc(self) -> float:
        yesterday = self.days.iloc[-1]
        if 'roc_5' in yesterday:
            # Rolling std over entire dataset
            roc_5_std = self.days['roc_5'].rolling(window=20).std().iloc[-1]
            if pd.notna(roc_5_std):
                return np.select(
                    [(yesterday['roc_5'] > 2 * roc_5_std), (yesterday['roc_5'] > 1 * roc_5_std)],
                    [2, 1],
                    default=0
                ).item()
        return 0

    def calculate_macd(self) -> float:
        yesterday = self.days.iloc[-1]
        if {'macd_line', 'macd_signal'}.issubset(yesterday):
            macd_diff = yesterday['macd_line'] - yesterday['macd_signal']
            # If MACD diff and line are positive, score 1 or 2 depending on how large the diff is
            if (macd_diff > 0) and (yesterday['macd_line'] > 0):
                return np.select(
                    [macd_diff > yesterday['macd_signal'] * MACD_SIGNAL_MULTIPLIER, macd_diff > yesterday['macd_signal']],
                    [2, 1],
                    0
                ).item()
        return 0

    def calculate_bb_position(self) -> float:
        yesterday = self.days.iloc[-1]
        bb_position = 0.0
        if ('bb_lower' in yesterday and 'bb_upper' in yesterday and (yesterday['bb_upper'] > yesterday['bb_lower'])):
            band_range = yesterday['bb_upper'] - yesterday['bb_lower']
            bb_position = (yesterday['close'] - yesterday['bb_lower']) / band_range

            return np.select(
                [
                    (bb_position >= 0.3) & (bb_position < 0.7),
                    (bb_position >= 0.1) & (bb_position < 0.3),
                    bb_position >= 0.85
                ],
                [2, 3, -1],
                default=0
            ).item()
        return 0

    def get_score(self) -> IndicatorScore:
        buy_score = 0.0

        buy_score += self.calculate_macd() * MACD_MULTIPLIER
        buy_score += self.calculate_roc() * ROC_MULTIPLIER
        buy_score += self.calculate_rsi() * RSI_MULTIPLIER
        buy_score += self.calculate_bb_position() * BB_MULTIPLIER
        sell_score = 0.0

        return IndicatorScore(buy_score, sell_score)
    
    def graph(self):
        pass

