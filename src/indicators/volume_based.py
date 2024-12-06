# Money Flow Index (MFI)
# On-Balance Volume (OBV)
# Volume Weighted Average Price (VWAP)

import numpy as np


class Volume_based:
    def __init__(self, data):
        self._data = data

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

