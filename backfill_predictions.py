"""
Backfill predictions on historical dates for ML training.

This script generates predictions on past trading dates that already have
future data available, allowing immediate grading for ML model training.

Usage:
    python backfill_predictions.py [--start DATE] [--count N] [--limit N]

Examples:
    # Generate 25 predictions starting from Jan 6, 2026
    python backfill_predictions.py --start 2026-01-06 --count 25

    # Limit to 100 symbols per date (faster testing)
    python backfill_predictions.py --start 2026-01-06 --count 5 --limit 100
"""

import argparse
import logging
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from bluehorseshoe.cli.context import create_cli_context
from bluehorseshoe.analysis.strategy import SwingTrader, StrategyContext
from bluehorseshoe.reporting.html_reporter import HTMLReporter
from bluehorseshoe.analysis.market_regime import MarketRegime
from bluehorseshoe.core.symbols import get_symbol_name_list


def get_next_trading_date(current_date: datetime) -> datetime:
    """Get next trading date (skip weekends)."""
    next_date = current_date + timedelta(days=1)
    # Skip weekends
    while next_date.weekday() >= 5:  # 5=Saturday, 6=Sunday
        next_date += timedelta(days=1)
    return next_date


def generate_trading_dates(start_date: str, count: int) -> list:
    """Generate list of trading dates starting from start_date."""
    dates = []
    current = datetime.strptime(start_date, "%Y-%m-%d")

    for _ in range(count):
        dates.append(current.strftime("%Y-%m-%d"))
        current = get_next_trading_date(current)

    return dates


def run_prediction_for_date(target_date: str, ctx, limit: int = None):
    """Run prediction for a specific date."""
    print(f"\n{'='*70}")
    print(f"PREDICTING: {target_date}")
    print(f"{'='*70}")

    try:
        # Initialize components
        trader = SwingTrader(database=ctx.db, report_writer=ctx.report_writer)

        # Get symbols
        symbols = get_symbol_name_list(database=ctx.db)
        if limit:
            # Randomize to avoid alphabetical bias
            random.shuffle(symbols)
            symbols = symbols[:limit]
            print(f"Limited to {limit} random symbols (avoiding alphabetical bias)")

        # Get market health
        market_health = MarketRegime.get_market_health(target_date=target_date, database=ctx.db)

        # Run predictions
        results = trader.swing_predict(
            target_date=target_date,
            symbols=symbols
        )

        # Generate report
        reporter = HTMLReporter(ctx.db, ctx.report_writer)

        # Get previous performance
        prev_perf = trader.get_previous_performance(target_date)

        # Generate HTML (date is first positional arg, not keyword)
        html_content = reporter.generate_report(
            target_date,
            market_health,
            results,
            [],  # charts
            prev_perf
        )

        email_html = reporter.generate_email_report(
            target_date,
            market_health,
            results,
            [],  # charts
            prev_perf
        )

        # Save reports
        full_path, email_path = reporter.save_both(html_content, email_html, f"report_{target_date}")

        print(f"✅ Success: {len(results)} candidates found")
        print(f"   Report: {full_path}")

        return True

    except Exception as e:
        print(f"❌ Failed: {e}")
        logging.error(f"Prediction failed for {target_date}: {e}", exc_info=True)
        return False


def main():
    parser = argparse.ArgumentParser(description="Backfill predictions for ML training")
    parser.add_argument("--start", default="2026-01-06", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--count", type=int, default=25, help="Number of dates to process")
    parser.add_argument("--limit", type=int, help="Limit symbols per date (for testing)")

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('/workspaces/BlueHorseshoe/src/logs/backfill_predictions.log', mode='w'),
            logging.StreamHandler(sys.stdout)
        ]
    )

    print("\n" + "="*70)
    print("BACKFILLING PREDICTIONS FOR ML TRAINING")
    print("="*70)
    print(f"Start Date: {args.start}")
    print(f"Count: {args.count} dates")
    if args.limit:
        print(f"Symbol Limit: {args.limit} per date")
    print("="*70)

    # Generate dates
    dates = generate_trading_dates(args.start, args.count)

    # Process each date
    success_count = 0
    failed_dates = []

    with create_cli_context() as ctx:
        for i, date in enumerate(dates, 1):
            print(f"\n[{i}/{len(dates)}] Processing {date}...")

            if run_prediction_for_date(date, ctx, limit=args.limit):
                success_count += 1
            else:
                failed_dates.append(date)

    # Summary
    print("\n" + "="*70)
    print("BACKFILL COMPLETE")
    print("="*70)
    print(f"Total Dates: {len(dates)}")
    print(f"Successful: {success_count}")
    print(f"Failed: {len(failed_dates)}")

    if failed_dates:
        print("\nFailed Dates:")
        for date in failed_dates:
            print(f"  - {date}")

    print("\n" + "="*70)
    print("NEXT STEPS")
    print("="*70)
    print("1. Verify scores in MongoDB:")
    print('   docker exec bluehorseshoe python -c "from bluehorseshoe.core.container import create_app_container; c = create_app_container(); db = c.get_database(); print(f\'Scores with metadata: {db[\"trade_scores\"].count_documents({\"metadata.entry_price\": {\"$exists\": True}})}\'); c.close()"')
    print("\n2. Train profit target models:")
    print("   docker exec bluehorseshoe python src/train_profit_target.py 10000")
    print("\n3. Verify models created:")
    print("   ls -lh src/models/ml_profit_target_*.joblib")
    print("="*70)


if __name__ == "__main__":
    main()
