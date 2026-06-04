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
from pathlib import Path

from sklearn.exceptions import ConvergenceWarning

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)

from bluehorseshoe.application.services import generate_reports, run_prediction, update_market_data
from bluehorseshoe.cli.context import create_cli_context
from bluehorseshoe.core.service import get_latest_market_date
from bluehorseshoe.core.symbol_repository import backfill_missing_overviews, get_symbols
from bluehorseshoe.data.historical_data import check_market_status
from bluehorseshoe.analysis.optimizer import WeightOptimizer
from bluehorseshoe.reporting.html_reporter import HTMLReporter

DEBUG_SYMBOL = 'ABVC'
DEBUG = False

def debug_test():
    """
    Debug function to test current theories.

    """
    pass    # pylint: disable=unnecessary-pass

if __name__ == "__main__":
    # -s : portfolio status snapshot. Short-circuits before the heavy
    # logging/warning setup so a quick peek doesn't truncate the daily
    # blueHorseshoe.log and returns in seconds, not minutes.
    if "-s" in sys.argv:
        from bluehorseshoe.trading.live_gateway_lifecycle import (
            refresh_token, snapshot_live_account,
        )
        live = "--live" in sys.argv
        refresh = "--refresh-token" in sys.argv
        if not (live or refresh):
            print("Use `./run.sh python src/gordon/swing_status.py` for the "
                  "paper account, `-s --live` for a live snapshot, or "
                  "`-s --refresh-token` to roll the live 7-day session "
                  "(triggers 2FA on your phone).", file=sys.stderr)
            sys.exit(2)
        if refresh:
            sys.exit(refresh_token())
        sys.exit(snapshot_live_account())

    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(os.path.join(_REPO_ROOT, 'src', 'logs', 'blueHorseshoe.log'), mode='w'),
            logging.StreamHandler(sys.stdout)
        ],
        force=True
    )
    logging.getLogger('pymongo').setLevel(logging.WARNING)

    logging.info('Starting BlueHorseshoe at %s...', time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
    start_time = time.time()

    # Logfire observability. No-op without LOGFIRE_TOKEN (safe on dev machines).
    # Bounded against exporter hangs — see docs/planning/LOGFIRE_FAILSAFE_BUG.md
    # (2026-05-30: a CLOSE_WAIT on the OTLP socket wedged the main thread for 1h
    # because the BatchSpanProcessor flush is OUTSIDE the try/except).
    os.environ.setdefault("OTEL_EXPORTER_OTLP_TIMEOUT", "10")  # per-request, seconds
    try:
        import atexit  # pylint: disable=import-outside-toplevel
        import logfire  # pylint: disable=import-outside-toplevel
        logfire.configure(service_name="gordon", send_to_logfire="if-token-present",
                          inspect_arguments=False)
        # Bound the atexit flush so a wedged exporter can't hold the process open.
        atexit.register(lambda: logfire.force_flush(timeout_millis=5000))
        _LOGFIRE = logfire
    except Exception:  # pylint: disable=broad-exception-caught
        _LOGFIRE = None  # observability must never break the pipeline
    # NOTE: LogfireLoggingHandler intentionally NOT installed. Routing every INFO+
    # stdlib log through the OTLP exporter turned thousands of per-symbol log
    # lines into individual remote writes — the volume amplifier behind the hang.
    # The gordon.update / gordon.predict spans carry enough operational signal.

    def _span(name, **attrs):
        """Logfire span if configured, else a no-op context manager."""
        from contextlib import nullcontext  # pylint: disable=import-outside-toplevel
        return _LOGFIRE.span(name, **attrs) if _LOGFIRE else nullcontext()

    # Suppress specific warnings
    warnings.filterwarnings("ignore", category=UserWarning, message="Non-invertible starting MA parameters found. " +
                            "Using zeros as starting parameters.")
    warnings.filterwarnings("ignore", category=UserWarning, message="Non-stationary starting autoregressive parameters " +
                            "found. Using zeros as starting parameters.")
    warnings.filterwarnings("ignore", category=ConvergenceWarning,
                            message="Maximum Likelihood optimization failed to ")
    warnings.filterwarnings("ignore", category=ConvergenceWarning)

    # Arcade reports in src/logs/ are date-stamped and preserved across runs

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

        with _span("gordon.update", active_only=active_only), create_cli_context(read_only_store=False) as ctx:
            if "--refresh-overviews" in sys.argv:
                ov_limit = None
                if "--ov-limit" in sys.argv:
                    try:
                        ov_limit = int(sys.argv[sys.argv.index("--ov-limit") + 1])
                    except (ValueError, IndexError):
                        pass
                backfill_missing_overviews(
                    database=ctx.db,
                    limit=ov_limit,
                )

            update_market_data(
                database=ctx.db,
                store=ctx.store,
                recent=True,
                symbols=symbols_filter,
                active_only=active_only,
            )
            logging.info("Recent historical data updated.")
    elif "-b" in sys.argv:
        deep = "--deep" in sys.argv
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

        with create_cli_context(read_only_store=False) as ctx:
            update_market_data(
                database=ctx.db,
                store=ctx.store,
                recent=False,
                symbols=symbols_filter,
                deep=deep,
                resume=resume,
                limit=limit,
            )
            logging.info("Full historical data updated.")
    elif "-p" in sys.argv:
        logging.info('Predicting next midpoints...')
        with _span("gordon.predict"), create_cli_context() as ctx:
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

            # Progress callback for pipeline status tracking
            def _progress_cb(current, total, pct):
                try:
                    from pipeline_status import update_progress  # pylint: disable=import-outside-toplevel
                    update_progress(current, total)
                except Exception:  # pylint: disable=broad-exception-caught
                    pass  # Status tracking is best-effort

            report_data = run_prediction(
                database=ctx.db,
                config=ctx.config,
                report_writer=ctx.report_writer,
                store=ctx.store,
                target_date=target_date,
                enabled_indicators=enabled_indicators,
                aggregation=aggregation,
                symbols=symbols_filter,
                progress_callback=_progress_cb
            )

            # Generate HTML Report
            if report_data:
                report_paths = generate_reports(
                    database=ctx.db,
                    report_data=report_data,
                    include_arcade=True,
                )
                logging.info("HTML Report saved to %s", report_paths["path"])
                logging.info("Email-friendly report saved to %s", report_paths["email_path"])
                print(f"HTML Report generated: {report_paths['path']}")
                print(f"Email-friendly report: {report_paths['email_path']}")
                if "arcade_path" in report_paths:
                    logging.info("Arcade report saved to %s", report_paths["arcade_path"])
                    print(f"Arcade report: {report_paths['arcade_path']}")

                # ── Trade Idea Logging ─────────────────────────────
                idea_lookup = {}
                try:
                    from bluehorseshoe.trading.trade_idea_logger import TradeIdeaLogger  # pylint: disable=import-outside-toplevel
                    idea_logger = TradeIdeaLogger(database=ctx.db)
                    idea_count, idea_lookup = idea_logger.log_ideas(
                        candidates=report_data.get('candidates', []),
                        batch_date=target_date,
                        max_positions=ctx.config.paper_max_positions,
                        total_investment=ctx.config.paper_total_investment,
                    )
                    print(f"Trade ideas logged: {idea_count}")
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logging.error("Trade idea logging failed (non-fatal): %s", e)

                # ── Paper Trading ────────────────────────────────────
                # `--no-paper` forces paper trading off regardless of config.
                # Used by the score backfill, which replays historical dates
                # and must never submit live orders against today's market.
                # (An inline PAPER_TRADING_ENABLED=false env var cannot work:
                # run.sh re-exports .env over the caller's environment.)
                if "--no-paper" in sys.argv:
                    logging.info("Paper trading suppressed by --no-paper flag.")
                if ctx.config.paper_trading_enabled and "--no-paper" not in sys.argv:
                    try:
                        from bluehorseshoe.trading.paper_trader import PaperTrader, PaperTradeConfig  # pylint: disable=import-outside-toplevel
                        pt_config = PaperTradeConfig(
                            total_investment=ctx.config.paper_total_investment,
                            max_positions=ctx.config.paper_max_positions,
                            logs_path=ctx.config.logs_path,
                            slots_deep_oversold=ctx.config.paper_slots_deep_oversold,
                        )
                        paper_trader = PaperTrader(
                            ibkr_client=ctx.ibkr,
                            config=pt_config,
                            database=ctx.db,
                        )
                        paper_results = paper_trader.execute(
                            candidates=report_data.get('candidates', []),
                            target_date=target_date,
                            idea_lookup=idea_lookup,
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
            aaii_details = market_health.get('details', {}).get('AAII', {})
            if aaii_details:
                market_health['aaii_spread'] = aaii_details.get('bull_bear_spread', 'N/A')
                market_health['aaii_signal'] = aaii_details.get('signal', '')
            cnn_details = market_health.get('details', {}).get('CNN', {})
            if cnn_details:
                market_health['cnn_score'] = cnn_details.get('score', 'N/A')
                market_health['cnn_rating'] = cnn_details.get('rating', '')

            # 2. Fetch Scores
            from bluehorseshoe.core.scores import ScoreManager
            score_manager = ScoreManager(database=ctx.db)
            baseline_scores = score_manager.get_scores(target_date, strategy="baseline")
            mr_scores = score_manager.get_scores(target_date, strategy="mean_reversion")

            if not baseline_scores and not mr_scores:
                print(f"No scores found for {target_date}. Please run prediction first (-p).")
                sys.exit(0)

            # 3. Build Symbol Map (for exchange info)
            from bluehorseshoe.core.symbols import get_sentiment_score
            from bluehorseshoe.data.tiingo_news import get_tiingo_sentiment_score_with_count
            from bluehorseshoe.data.stocktwits import get_stocktwits_sentiment_score_with_count
            from bluehorseshoe.data.finviz_news import get_finviz_sentiment_score_with_count
            from bluehorseshoe.analysis.sentiment_normalizer import SentimentNormalizer
            all_symbols = get_symbols(database=ctx.db)
            symbol_map = {s['symbol']: s.get('exchange', 'Unknown') for s in all_symbols}

            # Set up sentiment normalizer for composite computation
            normalizer = SentimentNormalizer(database=ctx.db)
            normalizer.load_source_stats()

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
                    "actual_close": meta.get('actual_close', 0),
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
                    "actual_close": meta.get('actual_close', 0),
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
                    "actual_close": meta.get('actual_close', 0),
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
                    "actual_close": meta.get('actual_close', 0),
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

            # Compute sentiment composite for all candidates
            for c in candidates + connors_candidates:
                c["sentiment_composite"] = normalizer.composite(c)

            # Sort and Limit
            candidates.sort(key=lambda x: x['score'], reverse=True)
            top_candidates = candidates[:50] + connors_candidates

            # 5. Generate Report
            reporter = HTMLReporter(database=ctx.db)

            # Generate full interactive report
            html_content = reporter.generate_report(
                date=target_date,
                regime=market_health,
                candidates=top_candidates,
                charts=[],
            )

            # Generate email-friendly report (no JavaScript, no charts)
            email_html = reporter.generate_email_report(
                date=target_date,
                regime=market_health,
                candidates=top_candidates,
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
    elif "--motifs" in sys.argv:
        logging.info("Building motif catalog...")
        with create_cli_context() as ctx:
            from bluehorseshoe.analysis.curves.motif_catalog import build_motif_catalog  # pylint: disable=import-outside-toplevel

            symbols_filter = None
            if "--symbols" in sys.argv:
                try:
                    symbols_str = sys.argv[sys.argv.index("--symbols") + 1]
                    symbols_filter = [s.strip() for s in symbols_str.split(',')]
                except (ValueError, IndexError):
                    pass

            if symbols_filter:
                symbols = symbols_filter
            elif "--full" in sys.argv:
                all_syms = get_symbols(database=ctx.db)
                symbols = [s['symbol'] for s in all_syms]
            else:
                # Default: 200 most liquid symbols
                all_syms = get_symbols(database=ctx.db)
                symbols = [s['symbol'] for s in all_syms[:200]]

            n_workers = 4
            if "--workers" in sys.argv:
                try:
                    n_workers = int(sys.argv[sys.argv.index("--workers") + 1])
                except (ValueError, IndexError):
                    pass

            resume = "--resume" in sys.argv

            catalog = build_motif_catalog(
                store=ctx.store,
                symbols=symbols,
                database=ctx.db,
                n_workers=n_workers,
                resume=resume,
            )

            # Print top motifs
            if catalog:
                sorted_motifs = sorted(catalog.values(), key=lambda x: x['composite_score'], reverse=True)
                print(f"\nMotif catalog built: {len(catalog)} unique patterns")
                print(f"{'Motif Key':<30} {'Samples':>8} {'WinRate':>8} {'Edge':>8} {'Z-Score':>8} {'Composite':>10}")
                print("-" * 82)
                for m in sorted_motifs[:20]:
                    print(f"{m['motif_key']:<30} {m['sample_count']:>8} {m['win_rate']:>8.3f} "
                          f"{m['edge']:>8.3f} {m['edge_zscore']:>8.2f} {m['composite_score']:>10.4f}")
            else:
                print("No motifs met the minimum sample threshold.")
    elif "--journal-review" in sys.argv:
        logging.info("Generating daily trade review...")
        with create_cli_context() as ctx:
            try:
                jrv_idx = sys.argv.index("--journal-review")
                jrv_date = None
                if len(sys.argv) > jrv_idx + 1 and not sys.argv[jrv_idx + 1].startswith("-"):
                    jrv_date = sys.argv[jrv_idx + 1]
                if not jrv_date:
                    jrv_date = get_latest_market_date(database=ctx.db, store=ctx.store)

                from bluehorseshoe.trading.trade_journal_reporter import TradeJournalReporter  # pylint: disable=import-outside-toplevel
                reporter = TradeJournalReporter(database=ctx.db)
                result = reporter.generate_daily_review(jrv_date)
                reporter.print_daily_review(result)
            except Exception as e:  # pylint: disable=broad-exception-caught
                logging.error("Daily review failed: %s", e)
                print(f"Error: {e}")
                sys.exit(1)
    elif "--journal-weekly" in sys.argv:
        logging.info("Generating weekly trade summary...")
        with create_cli_context() as ctx:
            try:
                jw_idx = sys.argv.index("--journal-weekly")
                if len(sys.argv) <= jw_idx + 1:
                    print("Usage: python src/main.py --journal-weekly YYYY-MM-DD (week start)")
                    sys.exit(1)
                jw_date = sys.argv[jw_idx + 1]

                from bluehorseshoe.trading.trade_journal_reporter import TradeJournalReporter  # pylint: disable=import-outside-toplevel
                reporter = TradeJournalReporter(database=ctx.db)
                summary = reporter.generate_weekly_summary(jw_date)
                reporter.print_weekly_summary(summary)
            except Exception as e:  # pylint: disable=broad-exception-caught
                logging.error("Weekly summary failed: %s", e)
                print(f"Error: {e}")
                sys.exit(1)
    elif "--journal-reconcile" in sys.argv:
        logging.info("Running trade reconciliation...")
        with create_cli_context() as ctx:
            try:
                jr_idx = sys.argv.index("--journal-reconcile")
                jr_date = None
                if len(sys.argv) > jr_idx + 1 and not sys.argv[jr_idx + 1].startswith("-"):
                    jr_date = sys.argv[jr_idx + 1]

                from bluehorseshoe.trading.trade_reconciler import TradeReconciler  # pylint: disable=import-outside-toplevel
                reconciler = TradeReconciler(database=ctx.db)
                result = reconciler.reconcile(batch_date=jr_date)
                print(f"Reconciliation: {result['orders_matched']} orders matched, "
                      f"{result['fills_matched']} fills matched, "
                      f"{result['positions_created']} positions created, "
                      f"{result['positions_updated']} updated, "
                      f"{result['unmatched_fills']} unmatched fills")
            except Exception as e:  # pylint: disable=broad-exception-caught
                logging.error("Reconciliation failed: %s", e)
                print(f"Error: {e}")
                sys.exit(1)
    elif "--journal-import-ibkr" in sys.argv:
        logging.info("Importing executions from IBKR...")
        with create_cli_context() as ctx:
            try:
                from bluehorseshoe.trading.execution_importer import ExecutionImporter  # pylint: disable=import-outside-toplevel
                importer = ExecutionImporter(database=ctx.db, ibkr_client=ctx.ibkr)
                count = importer.import_from_ibkr()
                print(f"Imported {count} fills from IBKR")
            except Exception as e:  # pylint: disable=broad-exception-caught
                logging.error("IBKR execution import failed: %s", e)
                print(f"Error: {e}")
                sys.exit(1)
    elif "--journal-import-csv" in sys.argv:
        logging.info("Importing fills from CSV...")
        with create_cli_context() as ctx:
            try:
                jic_idx = sys.argv.index("--journal-import-csv")
                if len(sys.argv) <= jic_idx + 1:
                    print("Usage: python src/main.py --journal-import-csv PATH")
                    sys.exit(1)
                csv_file = sys.argv[jic_idx + 1]

                if "--legacy" in sys.argv:
                    from bluehorseshoe.trading.csv_legacy_importer import CSVLegacyImporter  # pylint: disable=import-outside-toplevel
                    importer = CSVLegacyImporter(database=ctx.db)
                    result = importer.import_file(csv_file)
                    print(f"Legacy import: {result['fills_imported']} fills, "
                          f"{result['positions_created']} positions, {result['errors']} errors")
                else:
                    from bluehorseshoe.trading.execution_importer import ExecutionImporter  # pylint: disable=import-outside-toplevel
                    importer = ExecutionImporter(database=ctx.db)
                    count = importer.import_from_csv(csv_file)
                    print(f"Imported {count} fills from CSV")
            except Exception as e:  # pylint: disable=broad-exception-caught
                logging.error("CSV import failed: %s", e)
                print(f"Error: {e}")
                sys.exit(1)
    elif "--journal-log-ideas" in sys.argv:
        # Retroactively log trade ideas from saved scores
        logging.info("Logging trade ideas from saved scores...")
        with create_cli_context() as ctx:
            try:
                jli_idx = sys.argv.index("--journal-log-ideas")
                jli_date = None
                if len(sys.argv) > jli_idx + 1 and not sys.argv[jli_idx + 1].startswith("-"):
                    jli_date = sys.argv[jli_idx + 1]
                if not jli_date:
                    jli_date = get_latest_market_date(database=ctx.db, store=ctx.store)
                    logging.info("No date provided, defaulting to latest: %s", jli_date)

                from bluehorseshoe.core.scores import ScoreManager  # pylint: disable=import-outside-toplevel
                score_manager = ScoreManager(database=ctx.db)
                baseline_scores = score_manager.get_scores(jli_date, strategy="baseline")
                mr_scores = score_manager.get_scores(jli_date, strategy="mean_reversion")

                if not baseline_scores and not mr_scores:
                    print(f"No scores found for {jli_date}. Run prediction first (-p).")
                    sys.exit(0)

                # Build candidate dicts from scores (same structure as -p output)
                jli_candidates = []
                for s in baseline_scores:
                    meta = s.get('metadata', {})
                    entry_price = meta.get('entry_price', 0)
                    if not entry_price:
                        continue
                    jli_candidates.append({
                        "symbol": s['symbol'],
                        "strategy": "Baseline",
                        "score": s['score'],
                        "close": entry_price,
                        "actual_close": meta.get('actual_close', 0),
                        "stop_loss": meta.get('stop_loss', 0),
                        "t1_target": entry_price * 1.02 if entry_price > 0 else 0,
                        "target": meta.get('take_profit', 0),
                        "ml_prob": meta.get('ml_win_prob', 0.0),
                        "sentiment": meta.get('sentiment', 0.0),
                        "reasons": [f"{k}={v:.1f}" for k, v in meta.get('components', {}).items() if v != 0],
                    })
                for s in mr_scores:
                    meta = s.get('metadata', {})
                    entry_price = meta.get('entry_price', 0)
                    if not entry_price:
                        continue
                    jli_candidates.append({
                        "symbol": s['symbol'],
                        "strategy": "MeanRev",
                        "score": s['score'],
                        "close": entry_price,
                        "actual_close": meta.get('actual_close', 0),
                        "stop_loss": meta.get('stop_loss', 0),
                        "t1_target": entry_price * 1.02 if entry_price > 0 else 0,
                        "target": meta.get('take_profit', 0),
                        "ml_prob": meta.get('ml_win_prob', 0.0),
                        "sentiment": meta.get('sentiment', 0.0),
                        "reasons": [f"{k}={v:.1f}" for k, v in meta.get('components', {}).items() if v != 0],
                    })

                jli_candidates.sort(key=lambda x: x['score'], reverse=True)

                from bluehorseshoe.trading.trade_idea_logger import TradeIdeaLogger  # pylint: disable=import-outside-toplevel
                idea_logger = TradeIdeaLogger(database=ctx.db)
                count, _ = idea_logger.log_ideas(
                    candidates=jli_candidates,
                    batch_date=jli_date,
                    max_positions=ctx.config.paper_max_positions,
                    total_investment=ctx.config.paper_total_investment,
                )
                print(f"Logged {count} trade ideas for {jli_date}")
            except Exception as e:  # pylint: disable=broad-exception-caught
                logging.error("Journal log ideas failed: %s", e)
                print(f"Error: {e}")
                sys.exit(1)
    elif "--evaluate" in sys.argv:
        logging.info("Evaluating matured signal hypotheses...")
        with create_cli_context() as ctx:
            try:
                ev_idx = sys.argv.index("--evaluate")
                eval_date = None
                if len(sys.argv) > ev_idx + 1 and not sys.argv[ev_idx + 1].startswith("-"):
                    eval_date = sys.argv[ev_idx + 1]

                from bluehorseshoe.analysis.hypothesis_engine import HypothesisEngine  # pylint: disable=import-outside-toplevel
                engine = HypothesisEngine(database=ctx.db, store=ctx.store)
                summaries = engine.run(as_of_date=eval_date)
                for s in summaries:
                    print(f"Batch {s['batch_date']}: {s['evaluated']} evaluated, "
                          f"outcomes: {s['outcomes']}")
                if not summaries:
                    print("No mature batches to evaluate.")
            except Exception as e:  # pylint: disable=broad-exception-caught
                logging.error("Hypothesis evaluation failed: %s", e)
                print(f"Error: {e}")
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
