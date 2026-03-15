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

    # Arcade reports in src/graphs/ are date-stamped and preserved across runs

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

        active_only = "--all" not in sys.argv  # active-only by default; use --all to override

        with create_cli_context() as ctx:
            if "--refresh-overviews" in sys.argv:
                from bluehorseshoe.core.symbols import backfill_overviews  # pylint: disable=import-outside-toplevel
                ov_limit = None
                if "--ov-limit" in sys.argv:
                    try:
                        ov_limit = int(sys.argv[sys.argv.index("--ov-limit") + 1])
                    except (ValueError, IndexError):
                        pass
                backfill_overviews(ctx.db, limit=ov_limit)

            build_all_symbols_history(BackfillConfig(recent=True, symbols=symbols_filter, active_only=active_only), database=ctx.db, store=ctx.store)
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
            build_all_symbols_history(BackfillConfig(recent=False, resume=resume, limit=limit, symbols=symbols_filter), database=ctx.db, store=ctx.store)
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
                target_date = get_latest_market_date(database=ctx.db, store=ctx.store)
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
                report_writer=ctx.report_writer,
                store=ctx.store
            )

            # Progress callback for pipeline status tracking
            def _progress_cb(current, total, pct):
                try:
                    from pipeline_status import update_progress  # pylint: disable=import-outside-toplevel
                    update_progress(current, total)
                except Exception:  # pylint: disable=broad-exception-caught
                    pass  # Status tracking is best-effort

            report_data = trader.swing_predict(
                target_date=target_date,
                enabled_indicators=enabled_indicators,
                aggregation=aggregation,
                symbols=symbols_filter,
                progress_callback=_progress_cb
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
                vix_details = regime_for_html.get('details', {}).get('VIX', {})
                if vix_details:
                    regime_for_html['vix_close'] = vix_details.get('close', 'N/A')
                    regime_for_html['vix_fear'] = vix_details.get('fear_level', '')

                reporter = HTMLReporter(database=ctx.db)

                # Generate full interactive report
                html_content = reporter.generate_report(
                    date=target_date,
                    regime=regime_for_html,
                    candidates=report_data.get('candidates', []),
                    charts=report_data.get('charts', []),
                    previous_performance=prev_perf
                )

                # Generate email-friendly report (no JavaScript, no charts)
                email_html = reporter.generate_email_report(
                    date=target_date,
                    regime=regime_for_html,
                    candidates=report_data.get('candidates', []),
                    previous_performance=prev_perf
                )

                # Save both versions
                full_path, email_path = reporter.save_both(html_content, email_html, f"report_{target_date}")
                logging.info("HTML Report saved to %s", full_path)
                logging.info("Email-friendly report saved to %s", email_path)
                print(f"HTML Report generated: {full_path}")
                print(f"Email-friendly report: {email_path}")

                # Generate arcade report
                arcade_html = reporter.generate_arcade_report(
                    date=target_date,
                    regime=regime_for_html,
                    candidates=report_data.get('candidates', []),
                    previous_performance=prev_perf
                )
                arcade_path = reporter.save_arcade(arcade_html, f"report_{target_date}_arcade.html")
                logging.info("Arcade report saved to %s", arcade_path)
                print(f"Arcade report: {arcade_path}")

                # ── Paper Trading ────────────────────────────────────
                if ctx.config.paper_trading_enabled:
                    try:
                        from bluehorseshoe.trading.paper_trader import PaperTrader, PaperTradeConfig  # pylint: disable=import-outside-toplevel
                        pt_config = PaperTradeConfig(
                            total_investment=ctx.config.paper_total_investment,
                            max_positions=ctx.config.paper_max_positions,
                            logs_path=ctx.config.logs_path,
                        )
                        paper_trader = PaperTrader(
                            ibkr_client=ctx.ibkr,
                            config=pt_config,
                            database=ctx.db,
                        )
                        paper_results = paper_trader.execute(
                            candidates=report_data.get('candidates', []),
                            target_date=target_date,
                        )
                        submitted = sum(1 for r in paper_results if r.status == "submitted")
                        skipped = sum(1 for r in paper_results if r.status == "skipped")
                        errors = sum(1 for r in paper_results if r.status == "error")
                        print(f"Paper trading: {submitted} submitted, {skipped} skipped, {errors} errors")
                        logging.info("Paper trading complete: %d submitted, %d skipped, %d errors",
                                     submitted, skipped, errors)
                    except Exception as e:  # pylint: disable=broad-exception-caught
                        logging.error("Paper trading failed (non-fatal): %s", e)
                        print(f"Paper trading error (non-fatal): {e}")
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
                target_date = get_latest_market_date(database=ctx.db, store=ctx.store)
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
            vix_details = market_health.get('details', {}).get('VIX', {})
            if vix_details:
                market_health['vix_close'] = vix_details.get('close', 'N/A')
                market_health['vix_fear'] = vix_details.get('fear_level', '')

            # 2. Fetch Scores
            from bluehorseshoe.core.scores import ScoreManager
            score_manager = ScoreManager(database=ctx.db)
            baseline_scores = score_manager.get_scores(target_date, strategy="baseline")
            mr_scores = score_manager.get_scores(target_date, strategy="mean_reversion")

            if not baseline_scores and not mr_scores:
                print(f"No scores found for {target_date}. Please run prediction first (-p).")
                sys.exit(0)

            # 3. Build Symbol Map (for exchange info)
            from bluehorseshoe.core.symbols import get_symbols_from_mongo, get_sentiment_score
            from bluehorseshoe.data.tiingo_news import get_tiingo_sentiment_score_with_count
            from bluehorseshoe.data.stocktwits import get_stocktwits_sentiment_score_with_count
            from bluehorseshoe.data.finviz_news import get_finviz_sentiment_score_with_count
            all_symbols = get_symbols_from_mongo(database=ctx.db)
            symbol_map = {s['symbol']: s.get('exchange', 'Unknown') for s in all_symbols}

            # 4. Construct Candidates
            candidates = []
            sentiment_cache = {}
            tiingo_sentiment_cache = {}
            stocktwits_sentiment_cache = {}
            finviz_sentiment_cache = {}

            # Process Baseline
            for s in baseline_scores:
                meta = s.get('metadata', {})
                if not meta.get('entry_price'):
                    continue
                sym = s['symbol']
                if sym not in sentiment_cache:
                    sentiment_cache[sym] = get_sentiment_score(sym, target_date, database=ctx.db)
                if sym not in tiingo_sentiment_cache:
                    tiingo_sentiment_cache[sym] = meta.get('sentiment_tiingo') if meta.get('sentiment_tiingo') else get_tiingo_sentiment_score_with_count(sym, target_date, database=ctx.db)[0]
                if sym not in stocktwits_sentiment_cache:
                    stocktwits_sentiment_cache[sym] = meta.get('sentiment_stocktwits') if meta.get('sentiment_stocktwits') else get_stocktwits_sentiment_score_with_count(sym, target_date, database=ctx.db)[0]
                if sym not in finviz_sentiment_cache:
                    finviz_sentiment_cache[sym] = meta.get('sentiment_finviz') if meta.get('sentiment_finviz') else get_finviz_sentiment_score_with_count(sym, target_date, database=ctx.db)[0]
                entry_price = meta.get('entry_price', 0)
                candidates.append({
                    "symbol": sym,
                    "exchange": symbol_map.get(sym, 'Unknown'),
                    "strategy": "Baseline",
                    "score": s['score'],
                    "close": entry_price,
                    "stop_loss": meta.get('stop_loss', 0),
                    "t1_target": entry_price * 1.02 if entry_price > 0 else 0,
                    "target": meta.get('take_profit', 0),
                    "ml_prob": meta.get('ml_win_prob', 0.0),
                    "sentiment": sentiment_cache[sym],
                    "sentiment_tiingo": tiingo_sentiment_cache[sym],
                    "sentiment_stocktwits": stocktwits_sentiment_cache[sym],
                    "sentiment_finviz": finviz_sentiment_cache[sym],
                    "reasons": [f"{k}={v:.1f}" for k, v in meta.get('components', {}).items() if v != 0]
                })

            # Process Mean Reversion
            for s in mr_scores:
                meta = s.get('metadata', {})
                if not meta.get('entry_price'):
                    continue
                sym = s['symbol']
                if sym not in sentiment_cache:
                    sentiment_cache[sym] = get_sentiment_score(sym, target_date, database=ctx.db)
                if sym not in tiingo_sentiment_cache:
                    tiingo_sentiment_cache[sym] = meta.get('sentiment_tiingo') if meta.get('sentiment_tiingo') else get_tiingo_sentiment_score_with_count(sym, target_date, database=ctx.db)[0]
                if sym not in stocktwits_sentiment_cache:
                    stocktwits_sentiment_cache[sym] = meta.get('sentiment_stocktwits') if meta.get('sentiment_stocktwits') else get_stocktwits_sentiment_score_with_count(sym, target_date, database=ctx.db)[0]
                if sym not in finviz_sentiment_cache:
                    finviz_sentiment_cache[sym] = meta.get('sentiment_finviz') if meta.get('sentiment_finviz') else get_finviz_sentiment_score_with_count(sym, target_date, database=ctx.db)[0]
                entry_price = meta.get('entry_price', 0)
                candidates.append({
                    "symbol": sym,
                    "exchange": symbol_map.get(sym, 'Unknown'),
                    "strategy": "MeanRev",
                    "score": s['score'],
                    "close": entry_price,
                    "stop_loss": meta.get('stop_loss', 0),
                    "t1_target": entry_price * 1.02 if entry_price > 0 else 0,
                    "target": meta.get('take_profit', 0),
                    "ml_prob": meta.get('ml_win_prob', 0.0),
                    "sentiment": sentiment_cache[sym],
                    "sentiment_tiingo": tiingo_sentiment_cache[sym],
                    "sentiment_stocktwits": stocktwits_sentiment_cache[sym],
                    "sentiment_finviz": finviz_sentiment_cache[sym],
                    "reasons": [f"{k}={v:.1f}" for k, v in meta.get('components', {}).items() if v != 0]
                })

            # Build Connors candidates from persisted metadata
            connors_seen = set()
            connors_candidates = []
            # Prefer MR scores (processed second, so iterate them first)
            for s in mr_scores:
                meta = s.get('metadata', {})
                if not meta.get('connors_flag'):
                    continue
                sym = s['symbol']
                if sym in connors_seen:
                    continue
                connors_seen.add(sym)
                entry_price = meta.get('entry_price', 0)
                if sym not in sentiment_cache:
                    sentiment_cache[sym] = get_sentiment_score(sym, target_date, database=ctx.db)
                if sym not in tiingo_sentiment_cache:
                    tiingo_sentiment_cache[sym] = meta.get('sentiment_tiingo') if meta.get('sentiment_tiingo') else get_tiingo_sentiment_score_with_count(sym, target_date, database=ctx.db)[0]
                if sym not in stocktwits_sentiment_cache:
                    stocktwits_sentiment_cache[sym] = meta.get('sentiment_stocktwits') if meta.get('sentiment_stocktwits') else get_stocktwits_sentiment_score_with_count(sym, target_date, database=ctx.db)[0]
                if sym not in finviz_sentiment_cache:
                    finviz_sentiment_cache[sym] = meta.get('sentiment_finviz') if meta.get('sentiment_finviz') else get_finviz_sentiment_score_with_count(sym, target_date, database=ctx.db)[0]
                connors_candidates.append({
                    "symbol": sym,
                    "exchange": symbol_map.get(sym, 'Unknown'),
                    "strategy": "Connors",
                    "score": s['score'],
                    "close": entry_price,
                    "stop_loss": meta.get('stop_loss', 0),
                    "t1_target": entry_price * 1.02 if entry_price > 0 else 0,
                    "target": meta.get('take_profit', 0),
                    "ml_prob": meta.get('ml_win_prob', 0.0),
                    "sentiment": sentiment_cache[sym],
                    "sentiment_tiingo": tiingo_sentiment_cache[sym],
                    "sentiment_stocktwits": stocktwits_sentiment_cache[sym],
                    "sentiment_finviz": finviz_sentiment_cache[sym],
                    "connors_rsi2": meta.get('connors_rsi2'),
                    "connors_sma200": meta.get('connors_sma200'),
                    "reasons": [f"{k}={v:.1f}" for k, v in meta.get('components', {}).items() if v != 0]
                })
            for s in baseline_scores:
                meta = s.get('metadata', {})
                if not meta.get('connors_flag'):
                    continue
                sym = s['symbol']
                if sym in connors_seen:
                    continue
                connors_seen.add(sym)
                entry_price = meta.get('entry_price', 0)
                if sym not in sentiment_cache:
                    sentiment_cache[sym] = get_sentiment_score(sym, target_date, database=ctx.db)
                if sym not in tiingo_sentiment_cache:
                    tiingo_sentiment_cache[sym] = meta.get('sentiment_tiingo') if meta.get('sentiment_tiingo') else get_tiingo_sentiment_score_with_count(sym, target_date, database=ctx.db)[0]
                if sym not in stocktwits_sentiment_cache:
                    stocktwits_sentiment_cache[sym] = meta.get('sentiment_stocktwits') if meta.get('sentiment_stocktwits') else get_stocktwits_sentiment_score_with_count(sym, target_date, database=ctx.db)[0]
                if sym not in finviz_sentiment_cache:
                    finviz_sentiment_cache[sym] = meta.get('sentiment_finviz') if meta.get('sentiment_finviz') else get_finviz_sentiment_score_with_count(sym, target_date, database=ctx.db)[0]
                connors_candidates.append({
                    "symbol": sym,
                    "exchange": symbol_map.get(sym, 'Unknown'),
                    "strategy": "Connors",
                    "score": s['score'],
                    "close": entry_price,
                    "stop_loss": meta.get('stop_loss', 0),
                    "t1_target": entry_price * 1.02 if entry_price > 0 else 0,
                    "target": meta.get('take_profit', 0),
                    "ml_prob": meta.get('ml_win_prob', 0.0),
                    "sentiment": sentiment_cache[sym],
                    "sentiment_tiingo": tiingo_sentiment_cache[sym],
                    "sentiment_stocktwits": stocktwits_sentiment_cache[sym],
                    "sentiment_finviz": finviz_sentiment_cache[sym],
                    "connors_rsi2": meta.get('connors_rsi2'),
                    "connors_sma200": meta.get('connors_sma200'),
                    "reasons": [f"{k}={v:.1f}" for k, v in meta.get('components', {}).items() if v != 0]
                })
            connors_candidates.sort(key=lambda x: x['score'], reverse=True)
            connors_candidates = connors_candidates[:10]

            # Sort and Limit
            candidates.sort(key=lambda x: x['score'], reverse=True)
            top_candidates = candidates[:50] + connors_candidates

            # 5. Generate Report
            # Calculate previous day's performance
            trader = SwingTrader(database=ctx.db, store=ctx.store)
            prev_perf = trader.get_previous_performance(target_date)

            reporter = HTMLReporter(database=ctx.db)

            # Generate full interactive report
            html_content = reporter.generate_report(
                date=target_date,
                regime=market_health,
                candidates=top_candidates,
                charts=[],
                previous_performance=prev_perf
            )

            # Generate email-friendly report (no JavaScript, no charts)
            email_html = reporter.generate_email_report(
                date=target_date,
                regime=market_health,
                candidates=top_candidates,
                previous_performance=prev_perf
            )

            # Save both versions
            full_path, email_path = reporter.save_both(html_content, email_html, f"report_{target_date}")
            logging.info("HTML Report regenerated at %s", full_path)
            logging.info("Email-friendly report regenerated at %s", email_path)
            print(f"HTML Report regenerated: {full_path}")
            print(f"Email-friendly report: {email_path}")

            # Generate arcade report
            arcade_html = reporter.generate_arcade_report(
                date=target_date,
                regime=market_health,
                candidates=top_candidates,
                previous_performance=prev_perf
            )
            arcade_path = reporter.save_arcade(arcade_html, f"report_{target_date}_arcade.html")
            logging.info("Arcade report regenerated at %s", arcade_path)
            print(f"Arcade report: {arcade_path}")
    elif "-t" in sys.argv:
        with create_cli_context() as ctx:
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

                from bluehorseshoe.analysis.backtest import Backtester, BacktestConfig, BacktestOptions, SplitExitConfig

                config = BacktestConfig(
                    target_profit_factor=target_profit,
                    stop_loss_factor=stop_loss,
                    hold_days=hold_days,
                    use_trailing_stop=use_trailing,
                    trailing_multiplier=trailing_mult
                )
                tester = Backtester(config=config, database=ctx.db, store=ctx.store)

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

                bt_max_workers = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else None
                use_saved_scores = "--rescore" not in sys.argv
                options = BacktestOptions(
                    strategy=strategy,
                    enabled_indicators=enabled_indicators,
                    aggregation=aggregation,
                    symbols=symbols_filter,
                    max_workers=bt_max_workers,
                    use_saved_scores=use_saved_scores,
                )

                # Split-exit mode (defaults to atr_tiered / Plan B)
                split_config = None
                if "--split" in sys.argv:
                    split_idx = sys.argv.index("--split")
                    # Mode arg is optional; default to atr_tiered
                    next_arg = sys.argv[split_idx + 1] if split_idx + 1 < len(sys.argv) else None
                    if next_arg in ('fixed_pct', 'atr_tiered'):
                        split_mode = next_arg
                    else:
                        split_mode = 'atr_tiered'
                    t1_pct = 0.02
                    t1_atr = 1.0
                    t2_atr = 2.0
                    if "--t1-pct" in sys.argv:
                        t1_pct = float(sys.argv[sys.argv.index("--t1-pct") + 1])
                    if "--t1-atr" in sys.argv:
                        t1_atr = float(sys.argv[sys.argv.index("--t1-atr") + 1])
                    if "--t2-atr" in sys.argv:
                        t2_atr = float(sys.argv[sys.argv.index("--t2-atr") + 1])
                    split_config = SplitExitConfig(
                        mode=split_mode,
                        t1_profit_pct=t1_pct,
                        t1_atr_multiple=t1_atr,
                        t2_atr_multiple=t2_atr,
                    )
                    logging.info("Split-exit mode: %s", split_mode)

                if "--end" in sys.argv:
                    end_date = sys.argv[sys.argv.index("--end") + 1]
                    interval = int(sys.argv[sys.argv.index("--interval") + 1]) if "--interval" in sys.argv else 7
                    logging.info("Running range backtest from %s to %s | Strategy: %s...", target_date, end_date, strategy)
                    tester.run_range_backtest(target_date, end_date, interval_days=interval, options=options, split_config=split_config)
                else:
                    logging.info("Running backtest for %s | Strategy: %s...", target_date, strategy)
                    tester.run_backtest(target_date, options=options, split_config=split_config)
            except (IndexError, ValueError) as e:
                logging.error("Invalid arguments for backtesting: %s", e)
                print("Usage: python main.py -t START_DATE [--end END_DATE] [--interval 7] [--target 1.01] [--stop 0.98] [--hold 3]")
    elif "-w" in sys.argv:
        logging.info("Running LOO weight analysis...")
        with create_cli_context() as ctx:
            try:
                w_idx = sys.argv.index("-w")
                start_date = sys.argv[w_idx + 1]

                end_date = None
                if "--end" in sys.argv:
                    end_date = sys.argv[sys.argv.index("--end") + 1]
                if not end_date:
                    end_date = get_latest_market_date(database=ctx.db, store=ctx.store)

                interval = 7
                if "--interval" in sys.argv:
                    interval = int(sys.argv[sys.argv.index("--interval") + 1])

                top_n = 50
                if "--top" in sys.argv:
                    top_n = int(sys.argv[sys.argv.index("--top") + 1])

                hold_days = 10
                if "--hold" in sys.argv:
                    hold_days = int(sys.argv[sys.argv.index("--hold") + 1])

                from bluehorseshoe.analysis.loo_analyzer import LOOAnalyzer, LOOConfig
                from bluehorseshoe.analysis.loo_report import print_console_report, export_csv

                loo_config = LOOConfig(
                    start_date=start_date,
                    end_date=end_date,
                    interval_days=interval,
                    top_n=top_n,
                    hold_days=hold_days,
                )

                symbols_filter = None
                if "--symbols" in sys.argv:
                    try:
                        symbols_str = sys.argv[sys.argv.index("--symbols") + 1]
                        symbols_filter = [s.strip() for s in symbols_str.split(',')]
                    except (ValueError, IndexError):
                        pass

                # Split-exit mode for LOO (defaults to atr_tiered / Plan B)
                from bluehorseshoe.analysis.backtest import SplitExitConfig as LOOSplitConfig
                loo_split_config = None
                if "--split" in sys.argv:
                    split_idx = sys.argv.index("--split")
                    next_arg = sys.argv[split_idx + 1] if split_idx + 1 < len(sys.argv) else None
                    if next_arg in ('fixed_pct', 'atr_tiered'):
                        loo_split_mode = next_arg
                    else:
                        loo_split_mode = 'atr_tiered'
                    loo_split_config = LOOSplitConfig(mode=loo_split_mode)
                    logging.info("LOO split-exit mode: %s", loo_split_mode)

                analyzer = LOOAnalyzer(database=ctx.db, config=loo_config)
                results = analyzer.run(symbols=symbols_filter, split_config=loo_split_config)

                if results:
                    print_console_report(results)
                    export_csv(results)
                else:
                    print("No results from LOO analysis.")

            except (IndexError, ValueError) as e:
                logging.error("Invalid arguments for LOO analysis: %s", e)
                print("Usage: python main.py -w START_DATE [--end END_DATE] [--interval 7] [--top 50] [--hold 10]")
    elif "-f" in sys.argv:
        logging.info("Running forward selection weight analysis...")
        with create_cli_context() as ctx:
            try:
                f_idx = sys.argv.index("-f")
                start_date = sys.argv[f_idx + 1]

                end_date = None
                if "--end" in sys.argv:
                    end_date = sys.argv[sys.argv.index("--end") + 1]
                if not end_date:
                    end_date = get_latest_market_date(database=ctx.db, store=ctx.store)

                interval = 7
                if "--interval" in sys.argv:
                    interval = int(sys.argv[sys.argv.index("--interval") + 1])

                top_n = 50
                if "--top" in sys.argv:
                    top_n = int(sys.argv[sys.argv.index("--top") + 1])

                hold_days = 10
                if "--hold" in sys.argv:
                    hold_days = int(sys.argv[sys.argv.index("--hold") + 1])

                min_improvement = 0.1
                if "--min-improvement" in sys.argv:
                    min_improvement = float(sys.argv[sys.argv.index("--min-improvement") + 1])

                from bluehorseshoe.analysis.forward_selector import ForwardSelector, ForwardConfig

                fwd_config = ForwardConfig(
                    start_date=start_date,
                    end_date=end_date,
                    interval_days=interval,
                    top_n=top_n,
                    hold_days=hold_days,
                    min_improvement=min_improvement,
                )

                symbols_filter = None
                if "--symbols" in sys.argv:
                    try:
                        symbols_str = sys.argv[sys.argv.index("--symbols") + 1]
                        symbols_filter = [s.strip() for s in symbols_str.split(',')]
                    except (ValueError, IndexError):
                        pass

                selector = ForwardSelector(database=ctx.db, config=fwd_config)
                results = selector.run(symbols=symbols_filter)

                if not results:
                    print("No results from forward selection.")

            except (IndexError, ValueError) as e:
                logging.error("Invalid arguments for forward selection: %s", e)
                print("Usage: python main.py -f START_DATE [--end END_DATE] [--interval 7] [--top 50] [--hold 10] [--min-improvement 0.1]")
    elif "-g" in sys.argv:
        logging.info("Running indicator impact analysis...")
        with create_cli_context() as ctx:
            try:
                g_idx = sys.argv.index("-g")
                start_date = sys.argv[g_idx + 1]

                end_date = None
                if "--end" in sys.argv:
                    end_date = sys.argv[sys.argv.index("--end") + 1]
                if not end_date:
                    end_date = get_latest_market_date(database=ctx.db, store=ctx.store)

                interval = 14
                if "--interval" in sys.argv:
                    interval = int(sys.argv[sys.argv.index("--interval") + 1])

                hold_days = 10
                if "--hold" in sys.argv:
                    hold_days = int(sys.argv[sys.argv.index("--hold") + 1])

                from bluehorseshoe.analysis.indicator_impact import IndicatorImpactAnalyzer, ImpactConfig

                impact_config = ImpactConfig(
                    start_date=start_date,
                    end_date=end_date,
                    interval_days=interval,
                    hold_days=hold_days,
                )

                symbols_filter = None
                if "--symbols" in sys.argv:
                    try:
                        symbols_str = sys.argv[sys.argv.index("--symbols") + 1]
                        symbols_filter = [s.strip() for s in symbols_str.split(',')]
                    except (ValueError, IndexError):
                        pass

                analyzer = IndicatorImpactAnalyzer(database=ctx.db, config=impact_config)
                results = analyzer.run(symbols=symbols_filter)

                if not results:
                    print("No results from indicator impact analysis.")

            except (IndexError, ValueError) as e:
                logging.error("Invalid arguments for indicator impact: %s", e)
                print("Usage: python main.py -g START_DATE [--end END_DATE] [--interval 14] [--hold 10]")
    elif "-o" in sys.argv:
        logging.info("Optimizing indicator weights...")
        WeightOptimizer().run_optimization()
    elif "-q" in sys.argv or "--ibkr-quote" in sys.argv:
        # IBKR real-time quote mode
        try:
            if "-q" in sys.argv:
                idx = sys.argv.index("-q")
            else:
                idx = sys.argv.index("--ibkr-quote")

            symbols = [a.upper() for a in sys.argv[idx + 1:] if not a.startswith("-")]
            if not symbols:
                print("Usage: python src/main.py -q SYMBOL [SYMBOL ...]")
                sys.exit(1)

            with create_cli_context() as ctx:
                client = ctx.ibkr

                if len(symbols) == 1:
                    quotes = [client.get_quote(symbols[0])]
                else:
                    quotes = client.get_quotes(symbols)

                for q in quotes:
                    if q.error:
                        print(f"  {q.symbol}: ERROR - {q.error}")
                    else:
                        last_str = f"${q.last:.2f}" if q.last is not None else "N/A"
                        bid_str = f"${q.bid:.2f}" if q.bid is not None else "N/A"
                        ask_str = f"${q.ask:.2f}" if q.ask is not None else "N/A"
                        open_str = f"${q.open:.2f}" if q.open is not None else "N/A"
                        high_str = f"${q.high:.2f}" if q.high is not None else "N/A"
                        low_str = f"${q.low:.2f}" if q.low is not None else "N/A"
                        vol_str = f"{q.volume:,}" if q.volume is not None else "N/A"
                        ts_str = q.timestamp.strftime("%H:%M:%S") if q.timestamp else "N/A"
                        print(f"  {q.symbol}: Last={last_str}  Bid={bid_str}  Ask={ask_str}  "
                              f"Open={open_str}  High={high_str}  Low={low_str}  "
                              f"Vol={vol_str}  @{ts_str}")

        except Exception as e:
            logging.error("IBKR quote error: %s", e)
            print(f"Error: {e}")
            sys.exit(1)
    elif "-m" in sys.argv or "--monitor" in sys.argv:
        # Watchlist monitor mode — polls IBKR quotes on a loop
        with create_cli_context() as ctx:
            from bluehorseshoe.data.watchlist_monitor import WatchlistMonitor, load_watchlist

            # Determine symbols: CLI --symbols override or watchlist file
            symbols = None
            if "--symbols" in sys.argv:
                try:
                    symbols_str = sys.argv[sys.argv.index("--symbols") + 1]
                    symbols = [s.strip().upper() for s in symbols_str.split(",")]
                except (ValueError, IndexError):
                    pass

            if not symbols:
                symbols = load_watchlist()

            if not symbols:
                print("No symbols to monitor. Provide --symbols or create src/watchlist.txt")
                sys.exit(1)

            csv_path = f"{ctx.config.logs_path}/watchlist_{time.strftime('%Y-%m-%d')}.csv"
            monitor = WatchlistMonitor(
                client=ctx.ibkr,
                symbols=symbols,
                csv_path=csv_path,
            )
            monitor.run()
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
            "swing trading midpoints, -t YYYY-MM-DD to backtest, -q SYMBOL to get IBKR "
            "real-time quotes, -m to monitor watchlist, -d to debug, or -b to build "
            "historical data."
        )
        print(USAGE_STRING)
        sys.exit(1)

    end_time = time.time()
    logging.info('Execution time: %.2f seconds', end_time - start_time)
    # Report writer cleanup is handled by CLI context manager for modes that use it
