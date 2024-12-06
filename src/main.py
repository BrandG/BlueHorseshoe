"""
Main module for the BlueHorseshoe project.

This module handles the initialization, training, and prediction of stock midpoints using historical data.
It also provides functionality for debugging, updating historical data, and predicting next midpoints.

Modules:
    logging: Provides logging capabilities.
    statistics: Provides functions for mathematical statistics.
    sys: Provides access to some variables used or maintained by the interpreter.
    time: Provides time-related functions.
    warnings: Provides a way to handle warnings.
    pandas: Provides data structures and data analysis tools.
    sklearn.exceptions: Provides exceptions for scikit-learn.
    globals: Provides global variables and functions.
    historical_data: Provides functions to build and load historical data.
    prediction: Provides functions to forecast the next midpoint.
    os: Provides a way of using operating system dependent functionality.
    flatness: Provides functions to analyze midpoints.
    nnPrediction: Provides functions to get neural network predictions.

Functions:
    debug_test(): Loads historical data for IBM, trains the StockMidpointPredictor model, and evaluates its performance.

    Loads historical data for IBM, trains the StockMidpointPredictor model, and evaluates its performance.

    This function performs the following steps:
    1. Loads historical data for IBM.
    2. Prepares the data for training.
    3. Initializes and trains the StockMidpointPredictor model.
    4. Predicts the next day's midpoint.
    5. Evaluates the model's performance and prints the RMSE.

    Returns:
        None

"""
import logging
import sys
import time
import warnings
import os
import pandas as pd

from sklearn.exceptions import ConvergenceWarning

from globals import ReportSingleton, get_mongo_client, get_symbol_name_list
from historical_data import build_all_symbols_history, load_historical_data
from indicators import volitility
from indicators.ichimoku import Ichimoku
from indicators.momentum_oscillators import MomentumOscillators
from indicators.short_term_trend import ShortTermTrend
from indicators.volume_based import VolumeBased

sys.argv = ["-d"]


def get_indicator_results(data):
    """
    Calculate various financial indicators based on the provided data.

    Args:
        data (pd.DataFrame): A DataFrame containing the financial data required for the calculations.

    Returns:
        dict: A dictionary containing the results of various financial indicators, including:
            - 'mfi': Money Flow Index
            - 'obv': On-Balance Volume
            - 'vwap': Volume Weighted Average Price
            - 'rsi': Relative Strength Index
            - 'stochastic_oscillator': Stochastic Oscillator
            - 'macd': Moving Average Convergence Divergence
            - 'atr': Average True Range
            - 'bb': Bollinger Bands
            - 'stdev': Standard Deviation Volatility
            - 'emas': Exponential Moving Average Signals
            - 'PP': Pivot Points
            - 'ichimoku': Ichimoku Cloud
            - 'buy': Aggregated buy signals from various indicators
            - 'sell': Aggregated sell signals from various indicators
            - 'hold': Hold signal from the Stochastic Oscillator
            - 'volatility': Aggregated volatility signals from various indicators
            - 'direction': Aggregated direction signals from OBV and VWAP
    """
    results = {}

    _volume_based = VolumeBased(data)
    results['mfi'] = _volume_based.get_mfi()
    results['obv'] = _volume_based.get_obv()
    results['vwap'] = _volume_based.get_volume_weighted_average_price()
    _momentum_oscillators = MomentumOscillators(data)
    results['rsi'] = _momentum_oscillators.get_rsi()
    results['stochastic_oscillator'] = _momentum_oscillators.get_stochastic_oscillator()
    results['macd'] = _momentum_oscillators.get_macd()
    _volitility = volitility.Volitility(data)
    results['atr'] = _volitility.get_atr()
    results['bb'] = _volitility.get_bollinger_bands()
    results['stdev'] = _volitility.get_standard_deviation_volatility()
    _short_term_trend = ShortTermTrend(data)
    results['emas'] = _short_term_trend.get_ema_signals()
    results['PP'] = _short_term_trend.get_pivot_points()
    results['ichimoku'] = Ichimoku(data).get_results()

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


def debug_test():
    """
    Debug function to test the StockMidpointPredictor model.

    This function performs the following steps:
    1. Loads historical price data for IBM.
    2. Prepares the data for model training.
    3. Initializes and trains the StockMidpointPredictor model with a lookback period of 30 days.
    4. Predicts the next day's midpoint price.
    5. Evaluates the model's performance using RMSE (Root Mean Square Error).

    The function also contains commented-out code for additional analysis and forecasting of stock symbols,
    including calculating flatness, average delta, and generating graphical representations of midpoints.

    Note: The commented-out code is not executed but provides a template for further analysis and reporting.

    Returns:
        None
    """

    symbols = get_symbol_name_list()
    results = {'buy': 0, 'sell': 0, 'hold': 0, 'volatility': 0, 'direction': 0}
    candidates = []
    for index, symbol in enumerate(symbols):
        price_data = load_historical_data(symbol)
        if price_data is None:
            print(f"Failed to load historical data for {symbol}.")
            return
        price_data = price_data['days'][:240]
        clipped_price_data = price_data[::-1]
        print(symbol)
        # clipped_price_data = clipped_price_data[:-21]
        data = pd.DataFrame([{
            'open': val['open'],
            'high': val['high'],
            'low': val['low'],
            'close': val['close'],
            'volume': val['volume'],
            'date': val['date']}
            for val in clipped_price_data])
        results = get_indicator_results(data)
        candidates.append({'symbol': symbol, 'buy': results['buy'], 'sell': results['sell'],
                           'hold': results['hold'], 'volatility': results['volatility'],
                           'direction': results['direction']})
        print(f'{(index*100/len(symbols)):.2f}%. {symbol} - Buy: {results["buy"]} - Sell: {results["sell"]} - '
              f'Hold: {results["hold"]} - Volatility: {results["volatility"]} - Direction: {results["direction"]}')
    sorted_candidates = sorted(
        candidates, key=lambda x: (-x['buy'], -x['direction'], -x['volatility']))
    print(sorted_candidates[:10])


if __name__ == "__main__":
    start_time = time.time()

    logging.basicConfig(filename='blueHorseshoe.log', filemode='w',
                        level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.getLogger('pymongo').setLevel(logging.WARNING)

    if get_mongo_client() is None:
        sys.exit(1)

    # Suppress specific warnings
    warnings.filterwarnings("ignore", category=UserWarning, message="Non-invertible starting MA parameters found. " +
                            "Using zeros as starting parameters.")
    warnings.filterwarnings("ignore", category=UserWarning, message="Non-stationary starting autoregressive parameters " +
                            "found. Using zeros as starting parameters.")
    warnings.filterwarnings("ignore", category=ConvergenceWarning,
                            message="Maximum Likelihood optimization failed to ")
    warnings.filterwarnings("ignore", category=ConvergenceWarning)

    # Clear the graphs directory
    GRAPHS_DIR = 'graphs'
    for filename in os.listdir(GRAPHS_DIR):
        file_path = os.path.join(GRAPHS_DIR, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                os.rmdir(file_path)
        except (OSError, IOError) as e:
            logging.error('Failed to delete %s. Reason: %s', file_path, e)

    if "-u" in sys.argv:
        build_all_symbols_history(recent=True)
        print("Historical data updated.")
    elif "-b" in sys.argv:
        build_all_symbols_history()
        print("Historical data updated.")
    elif "-p" in sys.argv:
        # ToDo - Implement prediction
        print('Predicting next midpoints...')
    elif "-d" in sys.argv:
        debug_test()
    else:
        print("Invalid arguments. Use -u to update historical data, -p to predict next midpoints, -d to debug, or -b to build historical data.")
        sys.exit(1)

    ReportSingleton().close()
    end_time = time.time()
    print(f'Execution time: {end_time - start_time:.2f} seconds')
