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

from bluehorseshoe.reporting.report_generator import ReportSingleton
from bluehorseshoe.core.globals import get_mongo_client
from bluehorseshoe.data.historical_data import build_all_symbols_history
from bluehorseshoe.analysis.strategy import SwingTrader
from bluehorseshoe.analysis.optimizer import WeightOptimizer

DEBUG_SYMBOL = 'ABVC'
DEBUG = False


def debug_test():
    """
    Debug function to test current theories.

    """
    pass    # pylint: disable=unnecessary-pass

if __name__ == "__main__":
    logging.basicConfig(filename='/workspaces/BlueHorseshoe/src/logs/blueHorseshoe.log', filemode='w',
                        level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.getLogger('pymongo').setLevel(logging.WARNING)

    logging.info('Starting BlueHorseshoe at %s...', time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
    start_time = time.time()

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

    logging.info('deleting graphs...')
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
        logging.info("Recent historical data updated.")
    elif "-b" in sys.argv:
        build_all_symbols_history(recent=False)
        logging.info("Full historical data updated.")
    elif "-p" in sys.argv:
        logging.info('Predicting next midpoints...')
        SwingTrader().swing_predict()
    elif "-t" in sys.argv:
        try:
            test_idx = sys.argv.index("-t")
            target_date = sys.argv[test_idx + 1]
            
            # Optional parameters
            target_profit = 1.01
            stop_loss = 0.98
            hold_days = 3
            
            if "--target" in sys.argv:
                target_profit = float(sys.argv[sys.argv.index("--target") + 1])
            if "--stop" in sys.argv:
                stop_loss = float(sys.argv[sys.argv.index("--stop") + 1])
            if "--hold" in sys.argv:
                hold_days = int(sys.argv[sys.argv.index("--hold") + 1])
            
            from bluehorseshoe.analysis.backtest import Backtester
            tester = Backtester(target_profit_factor=target_profit, 
                               stop_loss_factor=stop_loss, 
                               hold_days=hold_days)

            strategy = "baseline"
            if "--strategy" in sys.argv:
                strategy = sys.argv[sys.argv.index("--strategy") + 1]

            enabled_indicators = None
            if "--indicators" in sys.argv:
                enabled_indicators = [i.strip() for i in sys.argv[sys.argv.index("--indicators") + 1].split(",")]
            
            aggregation = "sum"
            if "--aggregation" in sys.argv:
                aggregation = sys.argv[sys.argv.index("--aggregation") + 1]

            if "--end" in sys.argv:
                end_date = sys.argv[sys.argv.index("--end") + 1]
                interval = int(sys.argv[sys.argv.index("--interval") + 1]) if "--interval" in sys.argv else 7
                logging.info("Running range backtest from %s to %s | Strategy: %s...", target_date, end_date, strategy)
                tester.run_range_backtest(target_date, end_date, interval_days=interval, strategy=strategy, 
                                         enabled_indicators=enabled_indicators, aggregation=aggregation)
            else:
                logging.info("Running backtest for %s | Strategy: %s...", target_date, strategy)
                tester.run_backtest(target_date, strategy=strategy, enabled_indicators=enabled_indicators, aggregation=aggregation)
        except (IndexError, ValueError) as e:
            logging.error("Invalid arguments for backtesting: %s", e)
            print("Usage: python main.py -t START_DATE [--end END_DATE] [--interval 7] [--target 1.01] [--stop 0.98] [--hold 3]")
    elif "-o" in sys.argv:
        logging.info("Optimizing indicator weights...")
        WeightOptimizer().run_optimization()
    elif "-d" in sys.argv:
        logging.info("Debugging...")
        debug_test()
    else:
        USAGE_STRING = "Invalid arguments. Use -u to update historical data, -p to predict next day swing trading midpoints, -t YYYY-MM-DD to backtest, -d " \
                                "to debug, or -b to build historical data."
        logging.error(USAGE_STRING)
        print(USAGE_STRING)
        sys.exit(1)

    end_time = time.time()
    logging.info('Execution time: %.2f seconds', end_time - start_time)
    ReportSingleton().close()
