"""
candlestick_indicators.py
This module provides the `CandlestickIndicator` class for detecting various candlestick patterns in financial data.
The class includes methods to identify specific candlestick patterns such as "Three White Soldiers", "Rising/Falling Three Methods",
"Marubozu", and "Belt Hold". It also calculates a combined score based on the detected patterns.
Classes:
    CandlestickIndicator: A class for detecting candlestick patterns and calculating a combined score.
Constants:
    self.weights['RISE_FALL_3_METHODS_MULTIPLIER'] (float): Multiplier for the "Rising/Falling Three Methods" pattern score.
    self.weights['THREE_WHITE_SOLDIERS_MULTIPLIER'] (float): Multiplier for the "Three White Soldiers" pattern score.
    self.weights['MARUBOZU_MULTIPLIER'] (float): Multiplier for the "Marubozu" pattern score.
    self.weights['BELT_HOLD_MULTIPLIER'] (float): Multiplier for the "Belt Hold" pattern score.
Usage example:
    data = pd.DataFrame({
        'open': [...],
        'high': [...],
        'low': [...],
        'close': [...]
    })
    indicator = CandlestickIndicator(data)
    score = indicator.calculate_score()
"""
from matplotlib import pyplot as plt
import numpy as np
import pandas as pd
import talib
import mplfinance as mpf #pylint: disable=import-error
from typing import Optional

from bluehorseshoe.reporting.report_generator import GraphData, graph
from bluehorseshoe.analysis.indicators.indicator import Indicator, IndicatorScore
from bluehorseshoe.core.config import weights_config






class CandlestickIndicator(Indicator):
    """
    CandlestickIndicator class for detecting various candlestick patterns in financial data.
    This class provides methods to detect specific candlestick patterns such as "Three White Soldiers",
    "Rising/Falling Three Methods", "Marubozu", and "Belt Hold". It also calculates a combined score
    based on the detected patterns.
    Attributes:
        data (pd.DataFrame): DataFrame containing the candlestick data with columns 'open', 'close', 'high', and 'low'.
    Methods:
        _is_white_candle(open_price, close_price, threshold=0.0001) -> bool:
            Check if a candle is bullish (white).
        _has_small_shadow(open_price, high_price, low_price, close_price, body_ratio=0.3) -> bool:
            Check if the candle has relatively small shadows.
        _is_higher_open(prev_close, curr_open, threshold=0.0001) -> bool:
            Check if current candle opens higher than previous close.
        _detect_three_white_soldiers(body_ratio=0.3, price_threshold=0.0001) -> float:
        find_rise_fall_3_methods() -> float:
            Identifies the "Rising Three Methods" and "Falling Three Methods" candlestick patterns in the provided data.
        find_Marubozu() -> float:
        find_Belt_Hold() -> float:
        calculate_score() -> float:
    """

    def __init__(self, data: pd.DataFrame):
        self.weights = weights_config.get_weights('candlestick')
        self.required_cols = ['open', 'close', 'high', 'low']
        self.symbol = 'NONAME'
        super().__init__(data)

    def set_title(self, symbol: str) :
        """
        Sets the title for the candlestick indicator by appending an underscore to the given symbol.

        Args:
            symbol (str): The symbol to be used as the title.

        Returns:
            self: The instance of the class with the updated title.
        """
        self.symbol = symbol+'_'
        return self

    @staticmethod
    def is_white_candle(open_price, close_price, threshold=0.0001) -> bool:
        """Check if a candle is bullish (white)"""
        return close_price > open_price + threshold

    @staticmethod
    def has_small_shadow(open_price, high_price, low_price, close_price, body_ratio=0.3) -> bool:
        """
        Check if the candle has relatively small shadows
        body_ratio: maximum allowed ratio of shadow length to body length
        """
        body_length = abs(close_price - open_price)
        upper_shadow = high_price - max(open_price, close_price)
        lower_shadow = min(open_price, close_price) - low_price

        # Avoid division by zero
        if body_length == 0:
            return False

        return (upper_shadow / body_length) <= body_ratio and (lower_shadow / body_length) <= body_ratio

    @staticmethod
    def is_higher_open(prev_close, curr_open, threshold=0.0001) -> bool:
        """Check if current candle opens higher than previous close"""
        return curr_open > prev_close + threshold

    def detect_three_white_soldiers(self, body_ratio=0.3, price_threshold=0.0001) -> float:
        """
        Detects the "Three White Soldiers" candlestick pattern in the given data.
        The "Three White Soldiers" pattern is a bullish reversal pattern consisting of three consecutive long-bodied candlesticks that open within
            the previous candle's real body and close progressively higher.
        Args:
            body_ratio (float, optional): The maximum ratio of the shadow length to the body length for a candle to be considered having
                small shadows. Defaults to 0.3.
            price_threshold (float, optional): The minimum price difference to consider two prices as different. Defaults to 0.0001.
        Returns:
            float: Returns 1.0 if the "Three White Soldiers" pattern is detected, otherwise returns 0.0.
        """

        # Need at least 3 candles to detect pattern
        if len(self.days) < 3:
            return 0.0

        # Check last three consecutive candles
        candles = self.days.iloc[-2:]

        # Condition 1: All three candles must be white (bullish)
        all_white = all(
            self.is_white_candle(open_price, close_price, price_threshold)
            for open_price, close_price in zip(candles['open'], candles['close'])
        )

        # Condition 2: Each candle should have small shadows
        small_shadows = all(
            self.has_small_shadow(open_price, high_price, low_price, close_price, body_ratio)
            for open_price, high_price, low_price, close_price in zip(
                candles['open'], candles['high'], candles['low'], candles['close']
            )
        )

        # Condition 3: Each candle should open within the body of the previous candle
        higher_opens = all(
            self.is_higher_open(prev_close, curr_open, price_threshold)
            for prev_close, curr_open in zip(
                candles['close'].iloc[:-1], candles['open'].iloc[1:]
            )
        )

        # Condition 4: Each candle should close higher than the previous
        higher_closes = all(
            curr_close > prev_close + price_threshold
            for prev_close, curr_close in zip(
                candles['close'].iloc[:-1], candles['close'].iloc[1:]
            )
        )

        return 1.0 if all([all_white, small_shadows, higher_opens, higher_closes]) else 0.0

    def find_rise_fall_3_methods(self) -> float:
        """
        Identifies the "Rising Three Methods" and "Falling Three Methods" candlestick patterns
        in the provided data.

        This method uses the TA-Lib library to detect the patterns in the open, high, low, and
        close price data of the DataFrame stored in `self.data`.

        Returns:
            float: 
            - 1.0 if a bullish "Rising Three Methods" pattern is detected on the last bar.
            - -1.0 if a bearish "Falling Three Methods" pattern is detected on the last bar.
            - 0.0 if no pattern is detected on the last bar.
        """
        # Convert your columns to numpy arrays as required by TA-Lib
        opens = self.days['open'].values
        highs = self.days['high'].values
        lows = self.days['low'].values
        closes = self.days['close'].values

        rise_fall_3 = talib.CDLRISEFALL3METHODS(opens, highs, lows, closes) # type: ignore

        return 1.0 if rise_fall_3[-1] >= 100 else -1.0 if rise_fall_3[-1] <= -100 else 0.0

    def find_marubozu(self) -> float:
        """
        Identifies the Marubozu candlestick pattern in the provided data.

        A Marubozu candlestick pattern is a single candlestick with no shadows,
        indicating strong buying or selling pressure. This function uses the
        TA-Lib library to detect the pattern.

        Returns:
            float: 
                1.0 if a Bullish Marubozu pattern is detected,
               -1.0 if a Bearish Marubozu pattern is detected,
                0.0 if no pattern is detected.
        """
        marubozu = talib.CDLMARUBOZU( # type: ignore
            self.days['open'].values,
            self.days['high'].values,
            self.days['low'].values,
            self.days['close'].values)

        return 1.0 if marubozu[-1] >= 100 else -1.0 if marubozu[-1] <= -100 else 0.0

    def find_belt_hold(self) -> float:
        """
        Detects the Belt Hold candlestick pattern in the provided data.

        This method uses the TA-Lib library to identify the Belt Hold pattern in the
        candlestick data. The Belt Hold pattern can be either bullish or bearish.

        Returns:
            float: 
                1.0 if a Bullish Belt Hold pattern is detected,
                -1.0 if a Bearish Belt Hold pattern is detected,
                0.0 if no Belt Hold pattern is detected.
        """
        belt_hold = talib.CDLBELTHOLD( # type: ignore
            self.days['open'].values,
            self.days['high'].values,
            self.days['low'].values,
            self.days['close'].values)

        return 1.0 if belt_hold[-1] >= 100 else -1.0 if belt_hold[-1] <= -100 else 0.0

    def get_score(self, enabled_sub_indicators: Optional[list[str]] = None, aggregation: str = "sum") -> IndicatorScore:
        """
        Calculate the combined score based on various candlestick patterns.
        """
        buy_score = 1.0 if aggregation == "product" else 0.0
        active_count = 0

        sub_map = {
            'soldiers': (self.detect_three_white_soldiers, 'THREE_WHITE_SOLDIERS_MULTIPLIER'),
            'methods': (self.find_rise_fall_3_methods, 'RISE_FALL_3_METHODS_MULTIPLIER'),
            'marubozu': (self.find_marubozu, 'MARUBOZU_MULTIPLIER'),
            'belt_hold': (self.find_belt_hold, 'BELT_HOLD_MULTIPLIER')
        }

        for name, (func, weight_key) in sub_map.items():
            if enabled_sub_indicators is None or name in enabled_sub_indicators:
                score = func() * self.weights[weight_key]
                if aggregation == "product":
                    buy_score *= score
                else:
                    buy_score += score
                active_count += 1

        if active_count == 0 or (aggregation == "product" and buy_score == 0):
            buy_score = 0.0

        sell_score = 0.0
        return IndicatorScore(buy_score, sell_score)

    def graph(self) -> None:
        graph_data = GraphData(
            labels={'x_label':'Date', 'y_label':'Price', 'title':self.symbol+'Candlestick_Patterns'},
            curves=[],
        )
        price_list = self.days['close'].tolist()[-60:]
        if graph_data.candles:
            candle_data = {
                'Date': self.days['date'].tolist()[-60:],
                'Open': self.days['open'].tolist()[-60:],
                'High': self.days['high'].tolist()[-60:],
                'Low': self.days['low'].tolist()[-60:],
                'Close': self.days['close'].tolist()[-60:],
                'Volume': self.days['volume'].tolist()[-60:]
            }
            mpf.plot(candle_data, type='candle', style='charles', ax=plt.gca(), volume=True, title=self.symbol+'Candlestick_Patterns')

        graph_data.curves.append({"curve": price_list, "color": "k", "label": "Price"})
        found_one = False

        def mask_curve(curve, exclude_last_n):
            deleted_length = len(curve) - exclude_last_n
            masked_curve = [np.nan] * deleted_length + curve[deleted_length:]
            return masked_curve

        if self.detect_three_white_soldiers() > 0:
            found_one = True
            curve = (self.days['close']*0.9999).tolist()[-60:]
            graph_data.curves.append({"curve": mask_curve(curve, 3), "color": "b", "label": "Three White Soldiers"})
        if self.find_rise_fall_3_methods() > 0:
            found_one = True
            curve = (self.days['close']*0.9998).tolist()[-60:]
            graph_data.curves.append({"curve": mask_curve(curve, 3), "color": "g", "label": "Rise / Fall 3 Methods"})
        if self.find_marubozu() > 0:
            found_one = True
            curve = (self.days['close']*1.0001).tolist()[-60:]
            graph_data.curves.append({"curve": mask_curve(curve, 3), "color": "r", "label": "Marubozu"})
        if self.find_belt_hold() > 0:
            found_one = True
            curve = (self.days['close']*1.0002).tolist()[-60:]
            graph_data.curves.append({"curve": mask_curve(curve, 3), "color": "y", "label": "Belt Hold"})

        if found_one:
            graph(graph_data)
