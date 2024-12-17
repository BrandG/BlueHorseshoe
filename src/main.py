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
import random
import pandas as pd

from sklearn.exceptions import ConvergenceWarning

from globals import ReportSingleton, get_mongo_client, get_symbol_name_list
from historical_data import build_all_symbols_history, load_historical_data
from indicators.trend.ichimoku import Ichimoku
from indicators.indicator_aggregator import IndicatorAggregator
from predictors.predictor_aggergator import PredictorAggregator


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
    random_symbols = random.sample(symbols, 10)
    for index, symbol in enumerate(random_symbols):
        price_data = load_historical_data(symbol)
        if price_data is None:
            ReportSingleton().write(
                f"Failed to load historical data for {symbol}.")
            return

        price_data = price_data['days'][:240]
        clipped_price_data = price_data[::-1]

        data = pd.DataFrame([{
            'open': val['open'],
            'high': val['high'],
            'low': val['low'],
            'close': val['close'],
            'volume': val['volume'],
            'date': val['date']}
            for val in clipped_price_data])
        ichi = Ichimoku(data)
        ichi_results = ichi.value
        ichi.graph()
        ReportSingleton().write(f'{(index*100/len(random_symbols)):.2f}%. {symbol} - Buy: {ichi_results["buy"]} - Sell: {ichi_results["sell"]}')

def predict_temp():
    """
    Temporary Prediction function

    Returns:
        None
    """
    symbols = get_symbol_name_list()
    results = {'buy': 0, 'sell': 0, 'hold': 0, 'volatility': 0, 'direction': 0}
    candidates = []
    for index, symbol in enumerate(symbols):
        price_data = load_historical_data(symbol)
        if price_data is None:
            ReportSingleton().write(
                f"Failed to load historical data for {symbol}.")
            return

        price_data = price_data['days'][:240]
        clipped_price_data = price_data[::-1]

        data = pd.DataFrame([{
            'open': val['open'],
            'high': val['high'],
            'low': val['low'],
            'close': val['close'],
            'volume': val['volume'],
            'date': val['date']}
            for val in clipped_price_data])
        indicator_results = IndicatorAggregator(data).aggregate()
        predict_results = PredictorAggregator(data).aggregate()
        results = {**indicator_results, **predict_results}
        results['buy_minus_sell'] = results['buy'] - results['sell']

        candidates.append({'symbol': symbol, 'results': results})
        ReportSingleton().write(f'{(index*100/len(symbols)):.2f}%. {symbol} - Buy/Sell: {results["buy_minus_sell"]} - Buy: {results["buy"]}'
                                f' - Sell: {results["sell"]} - ' \
                                f'Hold: {results["hold"]} - Volatility: {results["volatility"]} - ' \
                                f'Direction: {results["direction"]} - Average drop: {results["drop"]}')
    sorted_candidates = sorted(candidates, key=lambda x: ( -x['results']['buy_minus_sell'], -x['results']['direction'], -x['results']['volatility']))
    for candidate in sorted_candidates[:10]:
        ReportSingleton().write(f"Candidate Symbol: {candidate['symbol']}")

if __name__ == "__main__":
    ReportSingleton().write(f'Starting BlueHorseshoe at {time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())}...')
    start_time = time.time()

    logging.basicConfig(filename='/workspaces/BlueHorseshoe/src/logs/blueHorseshoe.log', filemode='w',
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

    ReportSingleton().write('deleting graphs...')
    # Clear the graphs directory
    GRAPHS_DIR = '/workspaces/BlueHorseshoe/src/graphs'
    for filename in os.listdir(GRAPHS_DIR):
        try:
            file_path = os.path.join(GRAPHS_DIR, filename)
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                os.rmdir(file_path)
        except (OSError, IOError) as e:
            logging.error('Failed to delete. Reason: %s', e)

    if "-u" in sys.argv:
        build_all_symbols_history(recent=True)
        ReportSingleton().write("Recent historical data updated.")
    elif "-b" in sys.argv:
        build_all_symbols_history(recent=False)
        ReportSingleton().write("Full historical data updated.")
    elif "-p" in sys.argv:
        predict_temp()
        ReportSingleton().write('Predicting next midpoints...')
    elif "-d" in sys.argv:
        ReportSingleton().write("Debugging...")
        debug_test()
    else:
        ReportSingleton().write("Invalid arguments. Use -u to update historical data, -p to predict next midpoints, -d "
                                "to debug, or -b to build historical data.")
        sys.exit(1)

    end_time = time.time()
    ReportSingleton().write(f'Execution time: {end_time - start_time:.2f} seconds')
    ReportSingleton().close()
