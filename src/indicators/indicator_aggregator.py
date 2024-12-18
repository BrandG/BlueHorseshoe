"""
Module: indicator_aggregator

This module contains the IndicatorAggregator class which aggregates various financial indicators
to provide a comprehensive analysis of market data.

Classes:
    IndicatorAggregator: Aggregates multiple financial indicators and provides a summary of buy,
        sell, hold signals, volatility, direction, strength, and retracement.

"""
from indicators.momentum.momentum_indicator import MomentumIndicator
from indicators.others.others_indicator import OtherIndicators
from indicators.trend.trend_indicator import TrendIndicators
from indicators.volatility.volatility_indicator import VolatilityIndicators
from indicators.volume.volume_indicator import VolumeIndicators
from indicators.aroon import AROON


class IndicatorAggregator:
    """
    A class to aggregate multiple financial indicators and provide a summary of market data analysis.

    Attributes:
        _data (dict): The market data to be analyzed.

    Methods:
        __init__(data): Initializes the IndicatorAggregator with market data.
        update(data): Updates the market data.
        aggregate(data=None): Aggregates the financial indicators and returns a summary of the analysis.
    """

    _data = {}

    def __init__(self, data):
        """
        Initializes the IndicatorAggregator with market data.

        Args:
            data (dict): The market data to be analyzed.
        """
        self.update(data)

    def update(self, data):
        """
        Updates the market data.

        Args:
            data (dict): The new market data to be analyzed.
        """
        self._data = data

    def aggregate(self, data = None):
        """
        Aggregates the financial indicators and returns a summary of the analysis.

        Args:
            data (dict, optional): The market data to be analyzed. If not provided, the existing data will be used.

        Returns:
            dict: A dictionary containing the aggregated results of various financial indicators, including buy,
                sell, hold signals, volatility, direction, strength, and retracement.
        """

        if data is not None:
            self._data = data

        results = {}

        trend_indicator = TrendIndicators(self._data).value
        others_indicator = OtherIndicators(self._data).value
        momentum_indicator = MomentumIndicator(self._data).value
        volatility_indicator = VolatilityIndicators(self._data).value
        volume_indicator = VolumeIndicators(self._data).value
        results['aroon'] = AROON(self._data).value

        results['buy'] = (
            trend_indicator['buy'] +
            others_indicator['buy'] +
            momentum_indicator['buy'] +
            volatility_indicator['buy'] +
            volume_indicator['buy'] + \
            (1 if results['aroon']['buy'] else 0)
        )

        results['sell'] = (
            trend_indicator['sell'] +
            others_indicator['sell'] +
            momentum_indicator['sell'] +
            volatility_indicator['sell'] +
            volume_indicator['sell'] + \
            (1 if results['aroon']['sell'] else 0)
        )

        results['hold'] = momentum_indicator['hold']
        results['volatility'] = volatility_indicator['volatility']
        results['direction'] = volume_indicator['direction'] + trend_indicator['direction'] + \
            (1 if results['aroon']['direction'] == 'up' else 0) + \
            momentum_indicator['direction']
        results['strength'] = trend_indicator['strength']
        results['retracement'] = others_indicator['retracement']
        results['stop_loss_long'] = volatility_indicator['stop_loss_long']
        results['stop_loss_short'] = volatility_indicator['stop_loss_short']

        return results
