"""
claude_prediction Module
This module provides a class `ClaudePrediction` that implements various technical analysis indicators 
using the TA-Lib library. The indicators include Money Flow Index (MFI), On-Balance Volume (OBV), 
Volume Weighted Average Price (VWAP), Relative Strength Index (RSI), Stochastic Oscillator, and 
Moving Average Convergence Divergence (MACD).
Classes:
    ClaudePrediction: A class to calculate and interpret various technical analysis indicators.
    Attributes:
        _data (DataFrame): The input data containing 'high', 'low', 'close', and 'volume' columns.
    Methods:
        __init__(self, data): Initializes the ClaudePrediction class with the provided data.
        get_mfi(self): Calculates the Money Flow Index (MFI) and returns buy/sell signals based on thresholds.
        get_obv(self): Calculates the On-Balance Volume (OBV) and returns the direction of the OBV.
        volume_weighted_average_price(self): Calculates the Volume Weighted Average Price (VWAP) and returns the direction.
        get_rsi(self): Calculates the Relative Strength Index (RSI) and returns buy/sell signals based on thresholds.
        get_stochastic_oscillator(self): Calculates the Stochastic Oscillator and returns buy/sell/hold signals.
        get_macd(self): Calculates the Moving Average Convergence Divergence (MACD) and returns buy/sell signals.
"""

import numpy as np
import pandas as pd
import talib as ta
import matplotlib.pyplot as plt

from globals import GraphData, graph

class ClaudePrediction:
    """
    A class used to perform various technical analysis predictions on financial data.

    Attributes
    ----------
    _data : pandas.DataFrame
        A DataFrame containing the financial data with columns 'high', 'low', 'close', and 'volume'.

    Methods
    -------
    get_mfi():
        Calculates the Money Flow Index (MFI) and returns buy/sell signals based on overbought and oversold thresholds.
    
    get_obv():
        Calculates the On-Balance Volume (OBV) and returns the direction of the OBV movement.
    
    volume_weighted_average_price():
        Calculates the Volume Weighted Average Price (VWAP) and returns the direction of the price movement relative to VWAP.
    
    get_rsi():
        Calculates the Relative Strength Index (RSI) and returns buy/sell signals based on overbought and oversold thresholds.
    
    get_stochastic_oscillator():
        Calculates the Stochastic Oscillator and returns buy/sell/hold signals based on the crossover of %K and %D lines.
    
    get_macd():
        Calculates the Moving Average Convergence Divergence (MACD) and returns buy/sell signals based on the crossover of MACD and signal lines.
    """
    def __init__(self, data):
        self._data = data

    def get_results(self):
        """
        Calculate and return a dictionary of various technical analysis indicators and their signals.

        Returns:
            dict: A dictionary containing the following keys:
                - 'mfi': Money Flow Index (MFI) indicator results.
                - 'obv': On-Balance Volume (OBV) indicator results.
                - 'vwap': Volume Weighted Average Price (VWAP) indicator results.
                - 'rsi': Relative Strength Index (RSI) indicator results.
                - 'stochastic_oscillator': Stochastic Oscillator indicator results.
                - 'macd': Moving Average Convergence Divergence (MACD) indicator results.
                - 'atr': Average True Range (ATR) indicator results.
                - 'bb': Bollinger Bands indicator results.
                - 'stdev': Standard Deviation Volatility indicator results.
                - 'emas': Exponential Moving Average (EMA) signals.
                - 'ichimoku': Ichimoku Cloud indicator results.
                - 'PP': Pivot Points indicator results.
                - 'buy': Sum of buy signals from various indicators.
                - 'sell': Sum of sell signals from various indicators.
                - 'hold': Sum of hold signals from the Stochastic Oscillator.
                - 'volatility': Sum of high volatility signals from ATR, Bollinger Bands, and Standard Deviation.
                - 'direction': Sum of upward direction signals from OBV and VWAP.
        """
        results = {}

        results['mfi'] = self.get_mfi()
        results['obv'] = self.get_obv()
        results['vwap'] = self.volume_weighted_average_price()
        results['rsi'] = self.get_rsi()
        results['stochastic_oscillator'] = self.get_stochastic_oscillator()
        results['macd'] = self.get_macd()
        results['atr'] = self.get_atr()
        results['bb'] = self.get_bollinger_bands()
        results['stdev'] = self.get_standard_deviation_volatility()
        results['emas'] = self.get_ema_signals()
        results['ichimoku'] = self.get_ichimoku_cloud()
        results['PP'] = self.get_pivot_points()

        results['buy'] = (1 if results['mfi']['buy'] else 0) + \
            (1 if results['rsi']['buy'] else 0) + \
            (1 if results['stochastic_oscillator']['buy'] else 0) + \
            (1 if results['macd']['buy'] else 0) + \
            (1 if results['atr']['buy'] else 0) + \
            (1 if results['bb']['buy'] else 0) + \
            (1 if results['emas']['buy'] else 0) + \
            (1 if results['ichimoku']['buy'] else 0) + \
            (1 if results['PP']['buy'] else 0)

        results['sell'] = (1 if results['mfi']['sell'] else 0) + \
            (1 if results['rsi']['sell'] else 0) + \
            (1 if results['stochastic_oscillator']['sell'] else 0) + \
            (1 if results['macd']['sell'] else 0) + \
            (1 if results['atr']['sell'] else 0) + \
            (1 if results['bb']['sell'] else 0) + \
            (1 if results['emas']['sell'] else 0) + \
            (1 if results['ichimoku']['sell'] else 0) + \
            (1 if results['PP']['sell'] else 0)

        results['hold'] = (1 if results['stochastic_oscillator']['hold'] else 0)
        results['volatility'] = (1 if results['atr']['volatility'] == 'high' else 0) + \
            (1 if results['bb']['volatility'] == 'high' else 0) + \
            (1 if results['stdev']['volatility'] == 'high' else 0)
        results['direction'] = (1 if results['obv']['direction'] == 'up' else 0) + \
            (1 if results['vwap']['direction'] == 'up' else 0)
        return results

    def get_mfi(self, show = False):
        """
        Calculate the Money Flow Index (MFI) and determine buy/sell signals.

        The MFI is calculated using the high, low, close prices, and volume data over a time period of 14.
        The function returns a dictionary indicating whether to buy or sell based on the MFI value compared to
        the overbought and oversold thresholds.

        Returns:
            dict: A dictionary with 'buy' and 'sell' keys. The value for 'buy' is 'true' if the MFI is below the
                  oversold threshold, otherwise 'false'. The value for 'sell' is 'true' if the MFI is above the
                  overbought threshold, otherwise 'false'.
        """
        mfi_data = ta.MFI(self._data['high'], self._data['low'], self._data['close'], self._data['volume'], timeperiod=14).tolist() # type: ignore
        # pylint: disable=unused-variable
        def graph_this(mfi_data):
            # To Do: Fill this in
            print(mfi_data)
        if show:
            graph_this(mfi_data)

        mfi = mfi_data[-1]

        return {'buy': bool(mfi < np.percentile(mfi_data, 15)), 'sell': bool(mfi > np.percentile(mfi_data, 85))}

    def get_obv(self, show = False):
        """
        Calculate the On-Balance Volume (OBV) and determine its direction.

        The OBV is a technical analysis indicator that uses volume flow to predict changes in stock price.
        This function calculates the OBV based on the closing prices and volume data provided, and returns
        the direction of the OBV movement.

        Returns:
            dict: A dictionary containing the direction of the OBV movement with the key 'direction' and
                  value 'up' if the OBV is increasing, otherwise 'down'.
        """
        obv = ta.OBV(self._data['close'], self._data['volume']) # type: ignore
        # pylint: disable=unused-variable
        def graph_this(obv):
            # To Do: Fill this in
            print(obv)
        if show:
            graph_this(obv)

        return {'direction': 'up' if obv[0] > obv[1] else 'down'}

    def volume_weighted_average_price(self):
        """
        Calculate the Volume Weighted Average Price (VWAP) and determine the price direction.

        VWAP is calculated as the cumulative sum of the product of 'close' prices and 'volume' divided by the cumulative sum of 'volume'.

        Returns:
            dict: A dictionary with the key 'direction' indicating whether the price direction is 'up' or 'down'.
        """
        vwap = (self._data['close'] * self._data['volume']).cumsum() / self._data['volume'].cumsum()
        return {'direction': 'up' if self._data['close'].tolist()[-1] > vwap.tolist()[-1] else 'down'}

    def get_rsi(self, show = False):
        """
        Calculate the Relative Strength Index (RSI) and determine buy/sell signals.

        The function computes the RSI for the closing prices of the stock data over a 14-period window.
        It then determines the overbought and oversold thresholds based on the 85th and 15th percentiles
        of the RSI data, respectively.

        Returns:
            dict: A dictionary with 'buy' and 'sell' signals.
                  'buy' is 'true' if the RSI is below the oversold threshold, otherwise 'false'.
                  'sell' is 'true' if the RSI is above the overbought threshold, otherwise 'false'.
        """
        rsi_data = ta.RSI(self._data['close'], timeperiod=14).dropna() # type: ignore

        # pylint: disable=unused-variable
        def graph_this(rsi_data):
            # To Do: Fill this in
            print(rsi_data)
        if show:
            graph_this(rsi_data)

        rsi = rsi_data.tolist()[-1]

        return {'buy': bool(rsi < np.percentile(rsi_data, 15)), 'sell': bool(rsi > np.percentile(rsi_data, 85))}

    def get_stochastic_oscillator(self, show = False):
        """
        Calculate the Stochastic Oscillator for the given data.

        The Stochastic Oscillator is a momentum indicator comparing a particular closing price of a security to a range of its prices
            over a certain period of time.

        Returns:
            dict: A dictionary with keys 'buy', 'sell', and 'hold' indicating the trading signal based on the Stochastic Oscillator.
                - 'buy' (bool): True if a buy signal is generated, otherwise False.
                - 'sell' (bool): True if a sell signal is generated, otherwise False.
                - 'hold' (bool): True if a hold signal is generated, otherwise False.
        """
        slowk, slowd = ta.STOCH(self._data['high'], self._data['low'],self._data['close'], # type: ignore
                                fastk_period=5, slowk_period=3, slowk_matype=0,
                                slowd_period=3, slowd_matype=0)
        slowd = slowd.tolist()
        slowk = slowk.tolist()

        # pylint: disable=unused-variable
        def graph_this(slowd, slowk):
            # To Do: Fill this in
            print(slowd, slowk)
        if show:
            graph_this(slowd, slowk)

        buy = sell = hold = False
        if slowk[-1] > slowd[-1] and slowk[-2] <= slowd[-2]:
            buy = True
        elif slowk[-1] < slowd[-1] and slowk[-2] >= slowd[-2]:
            sell = True
        else:
            hold = True
        return {'buy': buy, 'sell': sell, 'hold': hold}

    def get_macd(self, show = False):
        """
        Calculate the Moving Average Convergence Divergence (MACD) and generate buy/sell signals.

        The MACD is calculated using the closing prices of the data. The function also converts the MACD
        and signal line values to percentage arrays relative to the closing prices.

        Returns:
            dict: A dictionary containing:
                - 'buy' (bool): True if a buy signal is generated, False otherwise.
                - 'sell' (bool): True if a sell signal is generated, False otherwise.
        """
        macd, signal, _ = ta.MACD(self._data['close'], fastperiod=12, slowperiod=26, signalperiod=9) # type: ignore
        macd_list = macd.tolist()
        signal_list = signal.tolist()

        # pylint: disable=unused-variable
        def graph_this(macd, signal):
            macd_list = (((macd / macd.max()) / 2) + 0.5).tolist()
            signal_list = (((signal / signal.max()) / 2) + 0.5).tolist()
            price_list = (self._data['close'] / self._data['close'].max()).tolist()
            buy_points = []
            sell_points = []
            for i in range(len(self._data['close'])):
                if macd_list[i] > signal_list[i] and macd_list[i-1] <= signal_list[i-1]:
                    buy_points.append({'x': i, 'y': price_list[i-1], 'color': 'green'})
                elif macd_list[i] < signal_list[i] and macd_list[i-1] >= signal_list[i-1]:
                    sell_points.append({'x': i, 'y': price_list[i-1], 'color': 'red'})
            points = buy_points + sell_points

            x_values = [pd.to_datetime(date).strftime('%Y-%m') for date in self._data['date']]
            graph(GraphData(x_label='Date', y_label='Percentage', title='MACD',
                                x_values=x_values, curves=[{'curve': macd_list, 'label': 'MACD', 'color':'orange'},
                                                            {'curve': signal_list, 'label': 'signal list', 'color':'red'},
                                                            {'curve': price_list, 'label': 'Close', 'color': 'green'}
                                                            ],
                                                            points=points
                                                            ))
        if show:
            graph_this(macd, signal)

        buy = macd_list[-1] > signal_list[-1] and macd_list[-2] <= signal_list[-2]
        sell = macd_list[-1] < signal_list[-1] and macd_list[-2] >= signal_list[-2]
        return {'buy': buy, 'sell': sell}

    def get_atr(self, multiplier=1.5, show = False):
        """
        Generate buy/sell signals based on ATR and report high volatility.

        This method uses the ATR to set stop-loss levels, identify potential breakout points, and report high volatility.

        Args:
            multiplier (float): The multiplier for setting stop-loss levels or identifying breakouts.

        Returns:
            dict: A dictionary with 'buy', 'sell', and 'high_volatility' signals.
                  'buy' is 'true' if a buy signal is generated, otherwise 'false'.
                  'sell' is 'true' if a sell signal is generated, otherwise 'false'.
                  'high_volatility' is 'true' if the current ATR is higher than the midpoint of the ATR list, otherwise 'false'.
        """
        atr = ta.ATR(self._data['high'], self._data['low'], self._data['close'], timeperiod=14) # type: ignore

        atr_value = atr.iloc[-1]
        close_price = self._data['close'].iloc[-1]

        # Calculate the midpoint of the ATR list
        atr_midpoint = np.median(atr)

        # Determine high volatility
        high_volatility = atr_value > atr_midpoint

        # Example of using ATR for stop-loss levels
        stop_loss_long = float((close_price - (multiplier * atr_value)).round(2))
        stop_loss_short = float((close_price + (multiplier * atr_value)).round(2))

        # Example of using ATR for breakout signals
        breakout_up = close_price + (multiplier * atr_value)
        breakout_down = close_price - (multiplier * atr_value)

        # Generate signals (this is just an example, you can customize the logic)
        buy_signal = bool(close_price > breakout_up)
        sell_signal = bool(close_price < breakout_down)

        # pylint: disable=unused-variable
        def graph_this(atr, high_volatility):
            price_data = (self._data['close'] / self._data['close'].max()).tolist()
            atr_list = (atr / atr.max()).tolist()
            points = []
            for i in range(len(self._data['close'])):
                if high_volatility[i]:
                    points.append({'x': i, 'y': price_data[i], 'color': 'green'})

            x_values = [pd.to_datetime(date).strftime('%Y-%m') for date in self._data['date']]
            graph(GraphData(x_label='Date', y_label='Percentage', title='ATR',
                                x_values=x_values, curves=[{'curve': atr_list, 'label': 'ATR', 'color':'blue'},
                                                            {'curve': price_data,
                                                            'label': 'Close', 'color': 'green'}],
                                                            points=points))
        if show:
            graph_this(atr, (atr > atr.mean()).tolist())

        return {'volatility': 'high' if high_volatility else 'low',
                'stop_loss_long': stop_loss_long,
                'stop_loss_short': stop_loss_short,
                'buy': buy_signal,
                'sell': sell_signal}

    def get_bollinger_bands(self, window=20, num_std=2, show = False):
        """
        Calculate the Bollinger Bands and generate buy/sell signals.

        The Bollinger Bands are calculated using the closing prices of the data. The function also calculates the
        moving average and the upper and lower bands based on the standard deviation.

        Args:
            window (int): The window size for the moving average.
            num_std (int): The number of standard deviations for the bands.
            
        Returns:
            dict: A dictionary containing:
                - 'buy' (bool): True if a buy signal is generated, False otherwise.
                - 'sell' (bool): True if a sell signal is generated, False otherwise.
        """
        upper_band, _, lower_band = ta.BBANDS(self._data['close'], timeperiod=window, nbdevup=num_std, nbdevdn=num_std, matype=0) # type: ignore

        buy = bool(self._data['close'].iloc[-1] < lower_band.iloc[-1])
        sell = bool(self._data['close'].iloc[-1] > upper_band.iloc[-1])

        # pylint: disable=unused-variable
        def graph_this(upper_band, lower_band):
            buy_list = (self._data['close'] < lower_band).tolist()
            sell_list = (self._data['close'] > upper_band).tolist()
            buy_points = []
            sell_points = []
            for i in range(len(self._data['close'])):
                if buy_list[i]:
                    buy_points.append({'x': i, 'y': self._data['close'].iloc[i], 'color': 'green'})
                elif sell_list[i]:
                    sell_points.append({'x': i, 'y': self._data['close'].iloc[i], 'color': 'red'})
            points = buy_points + sell_points

            x_values = [pd.to_datetime(date).strftime('%Y-%m') for date in self._data['date']]
            graph(GraphData(x_label='Date', y_label='Percentage', title='Boillinger Bands',
                                x_values=x_values, curves=[{'curve': upper_band, 'label': 'upper band', 'color':'orange'},
                                                            {'curve': lower_band, 'label': 'lower band', 'color':'red'},
                                                            {'curve': self._data['close'].tolist(),
                                                            'label': 'Close', 'color': 'green'}
                                                            ],
                                                            points=points))
        if show:
            graph_this(upper_band, lower_band)

        return {'buy': buy, 'sell': sell, 'volatility': 'high' if (buy or sell) else 'low'}

    def get_standard_deviation_volatility(self, period=20, show = False):
        """
        Calculate and report price volatility using the standard deviation.

        This method calculates the standard deviation of the closing prices over a specified period to determine price volatility.

        Args:
            period (int): The period for calculating the moving average and standard deviation.

        Returns:
            dict: A dictionary containing the current volatility value and a volatility level ('high' or 'low').
        """
        std_deviation = ta.STDDEV(self._data['close'], timeperiod=period) # type: ignore
        current_volatility = float(std_deviation.iloc[-1])
        volatility_level = 'high' if current_volatility > std_deviation.mean() else 'low'

        # pylint: disable=unused-variable
        def graph_this(std_deviation):
            price_data = (self._data['close'] / self._data['close'].max()).tolist()
            stdev_list = (std_deviation / std_deviation.max()).tolist()
            x_values = [pd.to_datetime(date).strftime('%Y-%m') for date in self._data['date']]
            graph(GraphData(x_label='Date', y_label='Percentage', title='Standard Deviation',
                                x_values=x_values, curves=[{'curve': stdev_list, 'label': 'stDev', 'color':'orange'},
                                                            {'curve': price_data, 'label': 'Close', 'color': 'green'}
                                                            ]))
        if show:
            graph_this(std_deviation)

        return {'current_stdev': current_volatility, 'volatility': volatility_level}

    # Short-Term Trend Indicators

    def get_ema_signals(self, show = False):
        """
        Determine buy/sell signals based on the 5-day and 20-day Exponential Moving Averages (EMAs).

        A buy signal is generated when the 5-day EMA crosses above the 20-day EMA.
        A sell signal is generated when the 5-day EMA crosses below the 20-day EMA.

        Returns:
            dict: A dictionary containing 'buy' and 'sell' signals.
                  'buy' is 'true' if a buy signal is generated, otherwise 'false'.
                  'sell' is 'true' if a sell signal is generated, otherwise 'false'.
        """
        ema_5 = ta.EMA(self._data['close'], timeperiod=5) # type: ignore
        ema_20 = ta.EMA(self._data['close'], timeperiod=20) # type: ignore

        # pylint: disable=unused-variable
        def graph_this(ema_5, ema_20):
            ema_5_list = ema_5.tolist()
            ema_20_list = ema_20.tolist()

            buy_points = []
            sell_points = []
            for i in range(len(self._data['close'])):
                if ema_5_list[i] > ema_20_list[i] and ema_5_list[i-1] <= ema_20_list[i-1]:
                    buy_points.append({'x': i, 'y': self._data['close'].iloc[i-1], 'color': 'green'})
                elif ema_5_list[i] < ema_20_list[i] and ema_5_list[i-1] >= ema_20_list[i-1]:
                    sell_points.append({'x': i, 'y': self._data['close'].iloc[i-1], 'color': 'red'})
            points = buy_points + sell_points

            x_values = [pd.to_datetime(date).strftime('%Y-%m') for date in self._data['date']]
            graph(GraphData(x_label='Date',
                y_label='Price',
                title='EMAs',
                x_values=x_values,
                curves=[
                    {'curve': self._data['close'].tolist(),'label': 'Close', 'color': 'blue'},
                    {'curve': ema_5.tolist(),'label': 'EMA-5', 'color': 'orange'},
                    {'curve': ema_20.tolist(),'label': 'EMA-20', 'color': 'red'},
                    ],
                points=points))
        if show:
            graph_this(ema_5, ema_20)

        buy_signal = bool(ema_5.iloc[-1] > ema_20.iloc[-1] and ema_5.iloc[-2] <= ema_20.iloc[-2])
        sell_signal = bool(ema_5.iloc[-1] < ema_20.iloc[-1] and ema_5.iloc[-2] >= ema_20.iloc[-2])

        return {'buy': buy_signal, 'sell': sell_signal}

    # Ichimoku Cloud
    def get_ichimoku_cloud(self, show = False):
        """
        Calculate the Ichimoku Cloud components for the given data.

        The Ichimoku Cloud is a technical analysis indicator that defines support and resistance,
        identifies trend direction, gauges momentum, and provides trading signals.

        This function calculates the following components:
        - Tenkan-sen (Conversion Line)
        - Kijun-sen (Base Line)
        - Senkou Span A (Leading Span A)
        - Senkou Span B (Leading Span B)

        The function also includes a nested function `graph_this` to plot the Ichimoku Cloud,
        but it is not called within this function.

        Returns:
            None
        """
        data=self._data
        high_9 = data['high'].rolling(window=9).max()
        low_9 = data['low'].rolling(window=9).min()
        tenkan_sen = (high_9 + low_9) / 2

        high_26 = data['high'].rolling(window=26).max()
        low_26 = data['low'].rolling(window=26).min()
        kijun_sen = (high_26 + low_26) / 2

        senkou_span_a = (tenkan_sen + kijun_sen) / 2

        high_52 = data['high'].rolling(window=52).max()
        low_52 = data['low'].rolling(window=52).min()
        senkou_span_b = (high_52 + low_52) / 2

        # Add 26 entries to the front of the data['close'] dataframe
        data['close'] = pd.concat([pd.Series([np.nan]*13), data['close']]).reset_index(drop=True)
        ichimoku_df = pd.DataFrame({
            'senkou_span_a': senkou_span_a,
            'senkou_span_b': senkou_span_b
        })

        # pylint: disable=unused-variable
        def graph_this(ichimoku_df):
            plt.figure(figsize=(14, 7))
            plt.plot(data.index, data['close'], label='Close')
            plt.plot(ichimoku_df.index, ichimoku_df['senkou_span_a'], label='Senkou Span A')
            plt.plot(ichimoku_df.index, ichimoku_df['senkou_span_b'], label='Senkou Span B')
            plt.fill_between(
                ichimoku_df.index,
                ichimoku_df['senkou_span_a'],
                ichimoku_df['senkou_span_b'],
                where=(ichimoku_df['senkou_span_a'] >= ichimoku_df['senkou_span_b']).tolist(),
                color='lightgreen', alpha=0.5)
            plt.fill_between(
                ichimoku_df.index,
                ichimoku_df['senkou_span_a'],
                ichimoku_df['senkou_span_b'],
                where=(ichimoku_df['senkou_span_a'] < ichimoku_df['senkou_span_b']).tolist(),
                color='lightcoral', alpha=0.5)
            plt.legend()
            plt.savefig('graphs/Ichimoku.png')
        if show:
            graph_this(ichimoku_df)
        return {'buy': bool(senkou_span_a.iloc[-1] > senkou_span_b.iloc[-1]),
                'sell': bool(senkou_span_a.iloc[-1] < senkou_span_b.iloc[-1]),
                'strength': float(abs(senkou_span_a.iloc[-1] - senkou_span_b.iloc[-1]).round(2))}

    # Pivot Points
    def get_pivot_points(self, show = False):
        """
        Calculate pivot points and support/resistance levels.

        Parameters:
            data (pd.DataFrame): DataFrame with columns 'high', 'low', 'close'.

        Returns:
            pd.DataFrame: DataFrame with pivot points and support/resistance levels.
        """
        pivot_points = pd.DataFrame(index=self._data.index)
        pivot_points['P'] = (self._data['high'] + self._data['low'] + self._data['close']) / 3
        pivot_points['R1'] = 2 * pivot_points['P'] - self._data['low']
        pivot_points['S1'] = 2 * pivot_points['P'] - self._data['high']
        pivot_points['R2'] = pivot_points['P'] + (self._data['high'] - self._data['low'])
        pivot_points['S2'] = pivot_points['P'] - (self._data['high'] - self._data['low'])
        pivot_points['R3'] = self._data['high'] + 2 * (pivot_points['P'] - self._data['low'])
        pivot_points['S3'] = self._data['low'] - 2 * (self._data['high'] - pivot_points['P'])

        def graph_this(pivot_points):
            buy_points = []
            sell_points = []
            for i in range(len(self._data['close'])):
                if self._data['close'][i] > pivot_points['P'][i] and self._data['close'][i-1] <= pivot_points['P'][i-1]:
                    buy_points.append({'x': i, 'y': self._data['close'].iloc[i-1], 'color': 'green'})
                elif self._data['close'][i] < pivot_points['P'][i] and self._data['close'][i-1] >= pivot_points['P'][i-1]:
                    sell_points.append({'x': i, 'y': self._data['close'].iloc[i-1], 'color': 'red'})
            points = buy_points + sell_points
            x_values = [pd.to_datetime(date).strftime('%Y-%m') for date in self._data['date']]
            graph(GraphData(x_label='Date',
                y_label='Price',
                title='Pivot Points',
                x_values=x_values,
                curves=[
                    {'curve': self._data['close'].tolist(),'label': 'Close', 'color': 'blue'},
                    {'curve': pivot_points['P'],'label': 'P', 'color': 'green'},
                    ], points=points))
        if show:
            graph_this(pivot_points)

        close_list = self._data['close'].tolist()
        pivot_points_list = pivot_points['P'].tolist()

        return {'buy':bool(close_list[-1] < pivot_points_list[-1]), 'sell':bool(close_list[-1] > pivot_points_list[-1])}
