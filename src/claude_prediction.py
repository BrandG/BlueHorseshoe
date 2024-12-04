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
import talib as ta

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

    def get_mfi(self):
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
        mfi_data = ta.MFI(self._data['high'], self._data['low'], self._data['close'], self._data['volume'], timeperiod=14).tolist()
        mfi = mfi_data[-1]

        overbought_threshold = np.percentile(mfi_data, 85)
        oversold_threshold = np.percentile(mfi_data, 15)

        return {'buy': 'true' if mfi < oversold_threshold else 'false', 'sell': 'true' if mfi > overbought_threshold else 'false'}

    def get_obv(self):
        """
        Calculate the On-Balance Volume (OBV) and determine its direction.

        The OBV is a technical analysis indicator that uses volume flow to predict changes in stock price.
        This function calculates the OBV based on the closing prices and volume data provided, and returns
        the direction of the OBV movement.

        Returns:
            dict: A dictionary containing the direction of the OBV movement with the key 'direction' and
                  value 'up' if the OBV is increasing, otherwise 'down'.
        """
        obv = ta.OBV(self._data['close'], self._data['volume'])
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

    def get_rsi(self):
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
        rsi_data = ta.RSI(self._data['close'], timeperiod=14).dropna()

        rsi = rsi_data.tolist()[-1]

        overbought_threshold = np.percentile(rsi_data, 85)
        oversold_threshold = np.percentile(rsi_data, 15)

        return {'buy': 'true' if rsi < oversold_threshold else 'false', 'sell': 'true' if rsi > overbought_threshold else 'false'}

    def get_stochastic_oscillator(self):
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
        slowk, slowd = ta.STOCH(self._data['high'], self._data['low'],self._data['close'],
                                fastk_period=5, slowk_period=3, slowk_matype=0,
                                slowd_period=3, slowd_matype=0)
        slowd = slowd.tolist()
        slowk = slowk.tolist()

        buy = sell = hold = False
        if slowk[-1] > slowd[-1] and slowk[-2] <= slowd[-2]:
            buy = True
        elif slowk[-1] < slowd[-1] and slowk[-2] >= slowd[-2]:
            sell = True
        else:
            hold = True
        return {'buy': buy, 'sell': sell, 'hold': hold}

    def get_macd(self):
        """
        Calculate the Moving Average Convergence Divergence (MACD) and generate buy/sell signals.

        The MACD is calculated using the closing prices of the data. The function also converts the MACD
        and signal line values to percentage arrays relative to the closing prices.

        Returns:
            dict: A dictionary containing:
                - 'buy' (bool): True if a buy signal is generated, False otherwise.
                - 'sell' (bool): True if a sell signal is generated, False otherwise.
        """
        macd, signal, _ = ta.MACD(self._data['close'], fastperiod=12, slowperiod=26, signalperiod=9)
        macd_list = macd.tolist()
        signal_list = signal.tolist()

        # convert macd and signal to percentage arrays
        macd = macd / self._data['close']
        signal = signal / self._data['close']

        buy = macd_list[-1] > signal_list[-1] and macd_list[-2] <= signal_list[-2]
        sell = macd_list[-1] < signal_list[-1] and macd_list[-2] >= signal_list[-2]
        return {'buy': buy, 'sell': sell}
