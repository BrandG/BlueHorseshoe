"""
Module: indicator_aggregator

This module contains the IndicatorAggregator class which aggregates various financial indicators
to provide a comprehensive analysis of market data.

Classes:
    IndicatorAggregator: Aggregates multiple financial indicators and provides a summary of buy,
        sell, hold signals, volatility, direction, strength, and retracement.

"""
from indicators.trend.average_directional_index import AverageDirectionalIndex
from indicators.trend.trend_indicator import TrendIndicators
from indicators.volatility.average_true_range import AverageTrueRange
from indicators.volatility.bollinger_bands import BollingerBands
from indicators.trend.commodity_channel_index import CCITrend
from indicators.trend.ema_crossover import EMACrossover
from indicators.others.fibonacci_retracement import FibonacciRetracement
from indicators.trend.ichimoku import Ichimoku
from indicators.momentum.macd import MACD
from indicators.volume.money_flow_index import MoneyFlowIndex
from indicators.volume.on_balance_volume import OnBalanceVolume
from indicators.others.pivot_points import PivotPoints
from indicators.momentum.relative_strength_index import RelativeStrengthIndex
from indicators.volatility.standard_deviation import StandardDeviation
from indicators.momentum.stochastic_oscillator import StochasticOscillator
from indicators.volume.volume_weighted_average_price import VolumeWeightedAveragePrice


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

        results['emas'] = EMACrossover(self._data).value
        results['rsi'] = RelativeStrengthIndex(self._data).value
        results['stochastic_oscillator'] = StochasticOscillator(self._data).value
        results['ichimoku'] = Ichimoku(self._data).value
        results['cci'] = CCITrend(self._data).value
        results['fib'] = FibonacciRetracement(self._data).value
        results['macd'] = MACD(self._data).value
        results['PP'] = PivotPoints(self._data).value
        results['mfi'] = MoneyFlowIndex(self._data).value
        results['obv'] = OnBalanceVolume(self._data).value
        results['vwap'] = VolumeWeightedAveragePrice(self._data).value
        results['atr'] = AverageTrueRange(self._data).value
        results['bb'] = BollingerBands(self._data).value
        results['stdev'] = StandardDeviation(self._data).value
        results['ADX'] = AverageDirectionalIndex(self._data).value

        trend_indicator = TrendIndicators(self._data).calculate()

        results['buy'] = trend_indicator['buy']
        results['buy'] += (1 if results['mfi']['buy'] else 0) + \
            (1 if results['rsi']['buy'] else 0) + \
            (1 if results['stochastic_oscillator']['buy'] else 0) + \
            (1 if results['macd']['buy'] else 0) + \
            (1 if results['atr']['buy'] else 0) + \
            (1 if results['bb']['buy'] else 0) + \
            (1 if results['PP']['buy'] else 0) + \
            (1 if results['fib']['buy'] else 0)

        results['sell'] = trend_indicator['sell']
        results['sell'] += (1 if results['mfi']['sell'] else 0) + \
            (1 if results['rsi']['sell'] else 0) + \
            (1 if results['stochastic_oscillator']['sell'] else 0) + \
            (1 if results['macd']['sell'] else 0) + \
            (1 if results['atr']['sell'] else 0) + \
            (1 if results['bb']['sell'] else 0) + \
            (1 if results['PP']['sell'] else 0) + \
            (1 if results['fib']['sell'] else 0)

        results['hold'] = (1 if results['stochastic_oscillator']['hold'] else 0)
        results['volatility'] = (1 if results['atr']['volatility'] == 'high' else 0) + \
            (1 if results['bb']['volatility'] == 'high' else 0) + \
            (1 if results['stdev']['volatility'] == 'high' else 0)
        results['direction'] = (1 if results['obv']['direction'] == 'up' else 0) + \
            (1 if results['vwap']['direction'] == 'up' else 0) + \
            (1 if results['ADX']['direction'] == 'up' else 0)
        results['strength'] = results['ADX']['strength']
        results['retracement'] = results['fib']['retracement']

        return results
