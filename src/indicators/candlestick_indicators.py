"""
candlestick_indicators.py
This module provides the `CandlestickIndicator` class for detecting various candlestick patterns in financial data.
The class includes methods to identify specific candlestick patterns such as "Three White Soldiers", "Rising/Falling Three Methods",
"Marubozu", and "Belt Hold". It also calculates a combined score based on the detected patterns.
Classes:
    CandlestickIndicator: A class for detecting candlestick patterns and calculating a combined score.
Constants:
    RISE_FALL_3_METHODS_MULTIPLIER (float): Multiplier for the "Rising/Falling Three Methods" pattern score.
    THREE_WHITE_SOLDIERS_MULTIPLIER (float): Multiplier for the "Three White Soldiers" pattern score.
    MARUBOZU_MULTIPLIER (float): Multiplier for the "Marubozu" pattern score.
    BELT_HOLD_MULTIPLIER (float): Multiplier for the "Belt Hold" pattern score.
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
import talib

RISE_FALL_3_METHODS_MULTIPLIER = 1.0
THREE_WHITE_SOLDIERS_MULTIPLIER = 1.0
MARUBOZU_MULTIPLIER = 1.0
BELT_HOLD_MULTIPLIER = 1.0

class CandlestickIndicator:
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

    def __init__(self, data):
        required_cols = ['open', 'close', 'high', 'low']
        self.data = data[required_cols].copy()

    @staticmethod
    def _is_white_candle(open_price, close_price, threshold=0.0001) -> bool:
        """Check if a candle is bullish (white)"""
        return close_price > open_price + threshold

    @staticmethod
    def _has_small_shadow(open_price, high_price, low_price, close_price, body_ratio=0.3) -> bool:
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
    def _is_higher_open(prev_close, curr_open, threshold=0.0001) -> bool:
        """Check if current candle opens higher than previous close"""
        return curr_open > prev_close + threshold

    def _detect_three_white_soldiers(self, body_ratio=0.3, price_threshold=0.0001) -> float:
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

        # Initialize result series
        df = self.data

        # Need at least 3 candles to detect pattern
        if len(df) < 3:
            return 0.0

        # Check last three consecutive candles
        candles = df.iloc[-2:]

        # Condition 1: All three candles must be white (bullish)
        all_white = all(
            self._is_white_candle(open_price, close_price, price_threshold)
            for open_price, close_price in zip(candles['open'], candles['close'])
        )

        # Condition 2: Each candle should have small shadows
        small_shadows = all(
            self._has_small_shadow(open_price, high_price, low_price, close_price, body_ratio)
            for open_price, high_price, low_price, close_price in zip(
                candles['open'], candles['high'], candles['low'], candles['close']
            )
        )

        # Condition 3: Each candle should open within the body of the previous candle
        higher_opens = all(
            self._is_higher_open(prev_close, curr_open, price_threshold)
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
        df = self.data

        # Convert your columns to numpy arrays as required by TA-Lib
        opens = df['open'].values
        highs = df['high'].values
        lows = df['low'].values
        closes = df['close'].values

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
        df = self.data

        marubozu = talib.CDLMARUBOZU( # type: ignore
            df['open'].values,
            df['high'].values,
            df['low'].values,
            df['close'].values)

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
        df = self.data

        belt_hold = talib.CDLBELTHOLD( # type: ignore
            df['open'].values,
            df['high'].values,
            df['low'].values,
            df['close'].values)

        return 1.0 if belt_hold[-1] >= 100 else -1.0 if belt_hold[-1] <= -100 else 0.0

    def calculate_score(self) -> float:
        """
        Calculate the combined score based on various candlestick patterns.

        This method detects several candlestick patterns and calculates a score for each pattern.
        The final score is a weighted sum of the individual pattern scores.

        Returns:
            float: The combined score of detected candlestick patterns.

        Patterns and their multipliers:
            - Three White Soldiers
            - Rising/Falling Three Methods
            - Marubozu
            - Belt Hold
        """
        three_white_soldiers = self._detect_three_white_soldiers() * THREE_WHITE_SOLDIERS_MULTIPLIER
        rise_fall_3_methods = self.find_rise_fall_3_methods() * RISE_FALL_3_METHODS_MULTIPLIER
        marubozu = self.find_marubozu() * MARUBOZU_MULTIPLIER
        belt_hold = self.find_belt_hold() * BELT_HOLD_MULTIPLIER

        # Combine scores
        score = three_white_soldiers + rise_fall_3_methods + marubozu + belt_hold

        return score
