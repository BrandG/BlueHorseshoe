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

from bluehorseshoe.reporting.html_reporter import HTMLReporter
from bluehorseshoe.cli.context import create_cli_context
from bluehorseshoe.core.service import get_latest_market_date
from bluehorseshoe.data.historical_data import build_all_symbols_history, check_market_status, BackfillConfig
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
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('/workspaces/BlueHorseshoe/src/logs/blueHorseshoe.log', mode='w'),
            logging.StreamHandler(sys.stdout)
        ],
        force=True
    )
    logging.getLogger('pymongo').setLevel(logging.WARNING)

    logging.info('Starting BlueHorseshoe at %s...', time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
    start_time = time.time()

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

        symbols_filter = None
        if "--symbols" in sys.argv:
            try:
                symbols_str = sys.argv[sys.argv.index("--symbols") + 1]
                # The symbol list needs to be in the format [{'symbol': 'SPY', 'name': 'SPDR S&P 500 ETF Trust'}, ...]
                symbols_filter = [{'symbol': s.strip(), 'name': ''} for s in symbols_str.split(',')]
            except (ValueError, IndexError):
                pass # Will default to all symbols

        with create_cli_context() as ctx:
            build_all_symbols_history(BackfillConfig(recent=True, symbols=symbols_filter), database=ctx.db)
            logging.info("Recent historical data updated.")
    elif "-b" in sys.argv:
        resume = "--resume" in sys.argv
        limit = None
        if "--limit" in sys.argv:
            try:
                limit = int(sys.argv[sys.argv.index("--limit") + 1])
            except (ValueError, IndexError):
                pass
        symbols_filter = None
        if "--symbols" in sys.argv:
            try:
                symbols_str = sys.argv[sys.argv.index("--symbols") + 1]
                symbols_filter = [{'symbol': s.strip(), 'name': ''} for s in symbols_str.split(',')]
            except (ValueError, IndexError):
                pass

        with create_cli_context() as ctx:
            build_all_symbols_history(BackfillConfig(recent=False, resume=resume, limit=limit, symbols=symbols_filter), database=ctx.db)
            logging.info("Full historical data updated.")
    elif "-p" in sys.argv:
        logging.info('Predicting next midpoints...')
        with create_cli_context() as ctx:
            target_date = None
            try:
                p_idx = sys.argv.index("-p")
                if len(sys.argv) > p_idx + 1 and not sys.argv[p_idx+1].startswith("-"):
                    target_date = sys.argv[p_idx + 1]
            except (ValueError, IndexError):
                pass

            if not target_date:
                target_date = get_latest_market_date(database=ctx.db)
                logging.info("No date provided for -p, defaulting to latest: %s", target_date)

            enabled_indicators = None
            if "--indicators" in sys.argv:
                enabled_indicators = [i.strip() for i in sys.argv[sys.argv.index("--indicators") + 1].split(",")]

            aggregation = "sum"
            if "--aggregation" in sys.argv:
                aggregation = sys.argv[sys.argv.index("--aggregation") + 1]

            symbols_filter = None
            if "--symbols" in sys.argv:
                try:
                    symbols_str = sys.argv[sys.argv.index("--symbols") + 1]
                    symbols_filter = [s.strip() for s in symbols_str.split(',')]
                except (ValueError, IndexError):
                    pass

            # Create SwingTrader with injected dependencies
            trader = SwingTrader(
                database=ctx.db,
                config=ctx.config,
                report_writer=ctx.report_writer
            )

            report_data = trader.swing_predict(
                target_date=target_date,
                enabled_indicators=enabled_indicators,
                aggregation=aggregation,
                symbols=symbols_filter
            )
            
            # Calculate previous day's performance
            prev_perf = trader.get_previous_performance(target_date)

            # Generate HTML Report
            if report_data:
                # Flatten the regime data for the reporter
                regime_for_html = report_data.get('regime', {})
                spy_details = regime_for_html.get('details', {}).get('SPY', {})
                regime_for_html['spy_price'] = spy_details.get('close', 'N/A')
                regime_for_html['spy_ma50'] = spy_details.get('ema50', 'N/A')
                regime_for_html['spy_ma200'] = spy_details.get('ema200', 'N/A')

                reporter = HTMLReporter(database=ctx.db)
                html_content = reporter.generate_report(
                    date=target_date,
                    regime=regime_for_html,
                    candidates=report_data.get('candidates', []),
                    charts=report_data.get('charts', []),
                    previous_performance=prev_perf
                )
                saved_path = reporter.save(html_content, filename=f"report_{target_date}.html")
                logging.info("HTML Report saved to %s", saved_path)
                print(f"HTML Report generated: {saved_path}")
    elif "-r" in sys.argv:
        # Generate Report from saved scores
        logging.info("Regenerating report from saved scores...")
        with create_cli_context() as ctx:
            target_date = None
            try:
                r_idx = sys.argv.index("-r")
                if len(sys.argv) > r_idx + 1 and not sys.argv[r_idx+1].startswith("-"):
                    target_date = sys.argv[r_idx + 1]
            except (ValueError, IndexError):
                pass

            if not target_date:
                target_date = get_latest_market_date(database=ctx.db)
                logging.info("No date provided for -r, defaulting to latest: %s", target_date)

            logging.info("Regenerating report for %s...", target_date)

            # 1. Market Regime
            from bluehorseshoe.analysis.market_regime import MarketRegime
            market_health = MarketRegime.get_market_health(target_date=target_date, database=ctx.db)

            # Flatten the regime details for the reporter
            spy_details = market_health.get('details', {}).get('SPY', {})
            market_health['spy_price'] = spy_details.get('close', 'N/A')
            market_health['spy_ma50'] = spy_details.get('ema50', 'N/A')
            market_health['spy_ma200'] = spy_details.get('ema200', 'N/A')

            # 2. Fetch Scores
            from bluehorseshoe.core.scores import ScoreManager
            score_manager = ScoreManager(database=ctx.db)
            baseline_scores = score_manager.get_scores(target_date, strategy="baseline")
            mr_scores = score_manager.get_scores(target_date, strategy="mean_reversion")

            if not baseline_scores and not mr_scores:
                print(f"No scores found for {target_date}. Please run prediction first (-p).")
                sys.exit(0)

            # 3. Build Symbol Map (for exchange info)
            from bluehorseshoe.core.symbols import get_symbols_from_mongo
            all_symbols = get_symbols_from_mongo(database=ctx.db)
            symbol_map = {s['symbol']: s.get('exchange', 'Unknown') for s in all_symbols}

            # 4. Construct Candidates
            candidates = []

            # Process Baseline
            for s in baseline_scores:
                meta = s.get('metadata', {})
                candidates.append({
                    "symbol": s['symbol'],
                    "exchange": symbol_map.get(s['symbol'], 'Unknown'),
                    "strategy": "Baseline",
                    "score": s['score'],
                    "close": meta.get('entry_price', 0),
                    "stop_loss": meta.get('stop_loss', 0),
                    "target": meta.get('take_profit', 0),
                    "ml_prob": meta.get('ml_win_prob', 0.0),
                    "reasons": [f"{k}={v:.1f}" for k, v in meta.get('components', {}).items() if v != 0]
                })

            # Process Mean Reversion
            for s in mr_scores:
                meta = s.get('metadata', {})
                candidates.append({
                    "symbol": s['symbol'],
                    "exchange": symbol_map.get(s['symbol'], 'Unknown'),
                    "strategy": "MeanRev",
                    "score": s['score'],
                    "close": meta.get('entry_price', 0),
                    "stop_loss": meta.get('stop_loss', 0),
                    "target": meta.get('take_profit', 0),
                    "ml_prob": meta.get('ml_win_prob', 0.0),
                    "reasons": [f"{k}={v:.1f}" for k, v in meta.get('components', {}).items() if v != 0]
                })

            # Sort and Limit
            candidates.sort(key=lambda x: x['score'], reverse=True)
            top_candidates = candidates[:50]

            # 5. Generate Report
            # Calculate previous day's performance
            trader = SwingTrader(database=ctx.db)
            prev_perf = trader.get_previous_performance(target_date)

            reporter = HTMLReporter(database=ctx.db)
            html_content = reporter.generate_report(
                date=target_date,
                regime=market_health,
                candidates=top_candidates,
                charts=[],
                previous_performance=prev_perf
            )
            saved_path = reporter.save(html_content, filename=f"report_{target_date}.html")
            logging.info("HTML Report regenerated at %s", saved_path)
            print(f"HTML Report regenerated: {saved_path}")
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
    # Report writer cleanup is handled by CLI context manager for modes that use it
