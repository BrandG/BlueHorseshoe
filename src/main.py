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

from sklearn.exceptions import ConvergenceWarning

from globals import ReportSingleton, get_mongo_client, get_symbol_name_list
from historical_data import build_all_symbols_history, load_historical_data

DEBUG_SYMBOL = 'ABVC'
DEBUG = False

def get_entry_exit_points(price_data):
    """
    Calculate entry and exit points for trading based on price data.

    This function analyzes the provided price data to determine potential entry and exit points for trading. 
    It calculates a score for the most recent day based on various indicators and sets the entry price, 
    stop loss, and take profit levels.

    Args:
        price_data (dict): A dictionary containing price data with the following structure:
            {
                'days': [
                    {
                        'close': float,
                        'ema_20': float,
                        'macd_line': float,
                        'macd_signal': float,
                        'adx': float,
                        'high': float,
                        'atr_14': float
                    },
                    ...
                ]
            }

    Returns:
        dict: The updated price data dictionary with added entry and exit points for the most recent day.
    """
    if len(price_data['days']) >= 2:
        yesterday = price_data['days'][-1]
        prev_day = price_data['days'][-2]

        yesterday['score'] = (
            (1 if yesterday['close'] > yesterday['ema_20'] else 0) +
            (1 if yesterday['macd_line'] > yesterday['macd_signal'] else 0) +
            (1 if yesterday['macd_line'] > 0 else 0) +
            (1 if yesterday['adx'] > 20 else 0)
        )

        yesterday['entry_price'] = max(yesterday['high'], prev_day['high']) + 0.2 * yesterday['atr_14']
        yesterday['stop_loss'] = yesterday['entry_price'] * 0.96
        yesterday['take_profit'] = yesterday['entry_price'] * 1.04

    return price_data

def debug_test():
    """
    Debug function to test current theories.

    """
    pass    # pylint: disable=unnecessary-pass

def predict_temp():
    """
    Temporary Prediction function

    Returns:
        None
    """
    symbols = get_symbol_name_list()
    results = []
    for _, symbol in enumerate(symbols):
        global DEBUG    # pylint: disable=global-statement
        DEBUG = symbol == DEBUG_SYMBOL
        price_data = load_historical_data(symbol)
        if price_data is None:
            ReportSingleton().write(f"Failed to load historical data for {symbol}.")
            return
        price_data = get_entry_exit_points(price_data)
        yesterday = price_data['days'][-1]
        if 'entry_price' in yesterday and yesterday['entry_price'] > 0 and 'stop_loss' in yesterday \
            and 'take_profit' in yesterday and 'score' in yesterday:
            results.append({'symbol': symbol, 'entry_price': yesterday['entry_price'], 'stop_loss': yesterday['stop_loss'],
                            'take_profit': yesterday['take_profit'], 'score': yesterday['score']})
            # ReportSingleton().write(f'{yesterday["date"]} - {symbol} - Entry: {yesterday["entry_price"]} - Stop-Loss: {yesterday["stop_loss"]} - '
            # f'Take-Profit: {yesterday["take_profit"]}')
    sorted_days = sorted(results, key=lambda x: x.get('score', 0), reverse=True)
    ReportSingleton().write('Top 10 buy candidates:')
    for i in range(min(10, len(sorted_days))):
        ReportSingleton().write(f'{sorted_days[i]["symbol"]} - Entry: {sorted_days[i]["entry_price"]} - Stop-Loss: {sorted_days[i]["stop_loss"]} -' \
                                f' Take-Profit: {sorted_days[i]["take_profit"]}')

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
