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
from bluehorseshoe.core.database import db
from bluehorseshoe.data.historical_data import build_all_symbols_history, check_market_status
from bluehorseshoe.analysis.strategy import SwingTrader
from bluehorseshoe.analysis.optimizer import WeightOptimizer

DEBUG_SYMBOL = 'ABVC'
DEBUG = False

def get_latest_market_date():
    """Find the most recent date available in historical_data."""
    database = db.get_db()
    latest = database.historical_prices.find_one({}, {'days.date': 1}, sort=[('days.date', -1)])
    return latest['days'][-1]['date'] if latest else None


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
        logging.info("Performing bellwether check...")
        while True:
            if check_market_status():
                break

            # Stop retrying at 3 AM
            if time.localtime().tm_hour == 3:
                logging.warning("Bellwether check failed. Time limit reached (3 AM). Aborting update.")
                print("Bellwether check failed. Time limit reached (3 AM). Aborting update.")
                sys.exit(0)

            logging.info("Market data not ready. Waiting 1 hour...")
            time.sleep(3600)

        build_all_symbols_history(recent=True)
        logging.info("Recent historical data updated.")
    elif "-b" in sys.argv:
        resume = "--resume" in sys.argv
        limit = None
        if "--limit" in sys.argv:
            try:
                limit = int(sys.argv[sys.argv.index("--limit") + 1])
            except (ValueError, IndexError):
                pass
        build_all_symbols_history(recent=False, resume=resume, limit=limit)
        logging.info("Full historical data updated.")
    elif "-p" in sys.argv:
        logging.info('Predicting next midpoints...')
        target_date = None
        try:
            p_idx = sys.argv.index("-p")
            if len(sys.argv) > p_idx + 1 and not sys.argv[p_idx+1].startswith("-"):
                target_date = sys.argv[p_idx + 1]
        except (ValueError, IndexError):
            pass

        if not target_date:
            target_date = get_latest_market_date()
            logging.info("No date provided for -p, defaulting to latest: %s", target_date)

        enabled_indicators = None
        if "--indicators" in sys.argv:
            enabled_indicators = [i.strip() for i in sys.argv[sys.argv.index("--indicators") + 1].split(",")]

        aggregation = "sum"
        if "--aggregation" in sys.argv:
            aggregation = sys.argv[sys.argv.index("--aggregation") + 1]

        SwingTrader().swing_predict(target_date=target_date, enabled_indicators=enabled_indicators, aggregation=aggregation)
    elif "-t" in sys.argv:
        try:
            test_idx = sys.argv.index("-t")
            target_date = sys.argv[test_idx + 1]

            # Optional parameters
            target_profit = 1.01
            stop_loss = 0.98
            hold_days = 3

            use_trailing = "--trailing" in sys.argv
            trailing_mult = 2.0
            if "--trailing-mult" in sys.argv:
                trailing_mult = float(sys.argv[sys.argv.index("--trailing-mult") + 1])

            if "--target" in sys.argv:
                target_profit = float(sys.argv[sys.argv.index("--target") + 1])
            if "--stop" in sys.argv:
                stop_loss = float(sys.argv[sys.argv.index("--stop") + 1])
            if "--hold" in sys.argv:
                hold_days = int(sys.argv[sys.argv.index("--hold") + 1])

            from bluehorseshoe.analysis.backtest import Backtester, BacktestConfig, BacktestOptions

            config = BacktestConfig(
                target_profit_factor=target_profit,
                stop_loss_factor=stop_loss,
                hold_days=hold_days,
                use_trailing_stop=use_trailing,
                trailing_multiplier=trailing_mult
            )
            tester = Backtester(config=config)

            strategy = "baseline"
            if "--strategy" in sys.argv:
                strategy = sys.argv[sys.argv.index("--strategy") + 1]

            enabled_indicators = None
            if "--indicators" in sys.argv:
                enabled_indicators = [i.strip() for i in sys.argv[sys.argv.index("--indicators") + 1].split(",")]

            aggregation = "sum"
            if "--aggregation" in sys.argv:
                aggregation = sys.argv[sys.argv.index("--aggregation") + 1]

            symbols_filter = None
            if "--symbols" in sys.argv:
                symbols_filter = [s.strip() for s in sys.argv[sys.argv.index("--symbols") + 1].split(",")]

            options = BacktestOptions(
                strategy=strategy,
                enabled_indicators=enabled_indicators,
                aggregation=aggregation,
                symbols=symbols_filter
            )

            if "--end" in sys.argv:
                end_date = sys.argv[sys.argv.index("--end") + 1]
                interval = int(sys.argv[sys.argv.index("--interval") + 1]) if "--interval" in sys.argv else 7
                logging.info("Running range backtest from %s to %s | Strategy: %s...", target_date, end_date, strategy)
                tester.run_range_backtest(target_date, end_date, interval_days=interval, options=options)
            else:
                logging.info("Running backtest for %s | Strategy: %s...", target_date, strategy)
                tester.run_backtest(target_date, options=options)
        except (IndexError, ValueError) as e:
            logging.error("Invalid arguments for backtesting: %s", e)
            print("Usage: python main.py -t START_DATE [--end END_DATE] [--interval 7] [--target 1.01] [--stop 0.98] [--hold 3]")
    elif "-o" in sys.argv:
        logging.info("Optimizing indicator weights...")
        WeightOptimizer().run_optimization()
    elif "-i" in sys.argv or "--intraday" in sys.argv:
        # Intraday check mode
        # Expects: -i SYMBOL ENTRY STOP TARGET
        try:
            # Find the index of the flag
            if "-i" in sys.argv:
                idx = sys.argv.index("-i")
            else:
                idx = sys.argv.index("--intraday")

            if len(sys.argv) < idx + 5:
                print("Usage: python src/main.py -i SYMBOL ENTRY STOP TARGET")
                sys.exit(1)

            symbol = sys.argv[idx + 1]
            entry = float(sys.argv[idx + 2])
            stop = float(sys.argv[idx + 3])
            target = float(sys.argv[idx + 4])

            # Import dynamically to avoid breaking if yfinance isn't installed for other modes
            sys.path.append(os.path.join(os.getcwd(), 'src'))
            from check_intraday_status import check_intraday
            check_intraday(symbol, entry, stop, target)

        except ValueError as e:
            print(f"Error parsing arguments: {e}")
            sys.exit(1)
    elif "-d" in sys.argv:
        logging.info("Debugging...")
        debug_test()
    else:
        USAGE_STRING = (
            "Invalid arguments. Use -u to update historical data, -p to predict next day "
            "swing trading midpoints, -t YYYY-MM-DD to backtest, -d to debug, or -b to "
            "build historical data."
        )
        print(USAGE_STRING)
        sys.exit(1)

    end_time = time.time()
    logging.info('Execution time: %.2f seconds', end_time - start_time)
    ReportSingleton().close()
