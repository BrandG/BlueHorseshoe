
import numpy as np
import talib as ta


class ClaudePrediction:
    _data = None

    def __init__(self, data):
        self._data = data

    # Money Flow Index (MFI)
    # https://www.quantifiedstrategies.com/how-to-build-a-profitable-money-flow-index-strategy-using-python/

    def get_mfis(self):
        mfi = ta.MFI(self._data['high'], self._data['low'], self._data['close'], self._data['volume'], timeperiod=14)
        self._data['MFI'] = mfi

        lookback_period = 100
        percentile_high = 85
        percentile_low = 15

        self._data['Overbought_Threshold'] = self._data['MFI'].rolling(window=lookback_period).apply(
            lambda x: np.percentile(x, percentile_high), raw=False)

        self._data['Oversold_Threshold'] = self._data['MFI'].rolling(window=lookback_period).apply(
            lambda x: np.percentile(x, percentile_low), raw=False)

        print(self._data['Overbought_Threshold'])
        # Eventually, we want to use a sophisticated way to tell whether the curve is going up or down
        # which I'm going to put in slope.py
        # For now, we will just use the 50-day moving average compared to the 200-day moving average
        fifty_day = self._data['close'].rolling(window=50).mean()
        two_hundred_day = self._data['close'].rolling(window=200).mean()
        # buy_count = list(filter(lambda x: x < low_threshold, mfi))
        # sell_count = list(filter(lambda x: x > high_threshold, mfi))
        # if fifty_day > two_hundred_day:
        #     # while the number of values lower than the low threshold is less than the number of values higher than the high threshold
        #     # we will keep increasing the high threshold and decreasing the low threshold
        #     while len(buy_count) < len(sell_count):
        #         high_threshold -= 1
        #         low_threshold += 1
        #         buy_count = list(filter(lambda x: x < low_threshold, mfi))
        #         sell_count = list(filter(lambda x: x > high_threshold, mfi))
        # else:
        #     while len(buy_count) < len(sell_count):
        #         high_threshold += 1
        #         low_threshold -= 1
        #         buy_count = list(filter(lambda x: x < low_threshold, mfi))
        #         sell_count = list(filter(lambda x: x > high_threshold, mfi))

    # On-Balance Volume (OBV)
    def on_balance_volume(self):
        obv = (self._data['close'].diff() > 0).apply(lambda x: x * self._data['volume']).cumsum()
        return obv

    # Volume Weighted Average Price (VWAP)
    def volume_weighted_average_price(self):
        vwap = (self._data['close'] * self._data['volume']).cumsum() / self._data['volume'].cumsum()
        return vwap
    
    # Relative Strength Index (RSI)
    def relative_strength_index(self, period=14):
        delta = self._data['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    # Stochastic Oscillator
    def stochastic_oscillator(self, period=14):
        low_min = self._data['low'].rolling(window=period).min()
        high_max = self._data['high'].rolling(window=period).max()
        k_percent = 100 * ((self._data['close'] - low_min) / (high_max - low_min))
        return k_percent

    # Moving Average Convergence Divergence (MACD)
    def moving_average_convergence_divergence(self, short_period=12, long_period=26, signal_period=9):
        short_ema = self._data['close'].ewm(span=short_period, adjust=False).mean()
        long_ema = self._data['close'].ewm(span=long_period, adjust=False).mean()
        macd = short_ema - long_ema
        signal = macd.ewm(span=signal_period, adjust=False).mean()
        return macd, signal

    # Average True Range (ATR)
    def average_true_range(self, period=14):
        tr1 = self._data['high'] - self._data['low']
        tr2 = abs(self._data['high'] - self._data['close'].shift())
        tr3 = abs(self._data['low'] - self._data['close'].shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        return atr

    # Bollinger Bands
    def bollinger_bands(self, period=20, std_dev=2):
        sma = self._data['close'].rolling(window=period).mean()
        rolling_std = self._data['close'].rolling(window=period).std()
        
