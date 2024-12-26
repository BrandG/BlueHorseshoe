"""
BlueHorseshoe Trading System

This module provides functionality for analyzing historical stock price data and predicting potential entry and exit points for trading. 
It includes functions for loading historical data, calculating trading signals, and generating reports.

Modules:
    - logging: For logging messages to a file.
    - sys: For system-specific parameters and functions.
    - time: For time-related functions.
    - warnings: For managing warnings.
    - os: For interacting with the operating system.
    - sklearn.exceptions: For handling specific exceptions from scikit-learn.
    - globals: Custom module for global variables and functions.
    - historical_data: Custom module for handling historical data.

Functions:
    - get_entry_exit_points(price_data): Calculate entry and exit points for trading based on price data.
    - debug_test(): Debug function to test current theories.
    - predict_temp(): Temporary prediction function to analyze symbols and generate trading signals.

"""
import logging
import sys
import time
import warnings
import os

from sklearn.exceptions import ConvergenceWarning

from globals import ReportSingleton, get_mongo_client
from historical_data import build_all_symbols_history
from swing_trading import swing_predict

DEBUG_SYMBOL = 'ABVC'
DEBUG = False


def debug_test():
    """
    Debug function to test current theories.

    """
    pass    # pylint: disable=unnecessary-pass

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
        swing_predict()
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
