"""
Maintenance utilities for updating symbols, history, and retraining models.
"""
import argparse
import logging
from tqdm import tqdm  # You might need to pip install tqdm
from requests.exceptions import RequestException
from pymongo.errors import PyMongoError

# Import our internal modules
from bluehorseshoe.analysis.ml_overlay import MLOverlayTrainer
from . import symbols
from .database import db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("maintenance.log"),
        logging.StreamHandler()
    ]
)

def update_symbol_universe():
    """
    Step 1: Get the latest list of active symbols from Alpha Vantage.
    """
    print("\n--- STEP 1: Updating Symbol Universe ---")
    try:
        result = symbols.refresh_symbols()
        status = result.get("status")
        count = result.get("count", 0)

        if status == "ok":
            logging.info("Symbol universe updated. Processed %s symbols. Database changes: %s", result.get('symbol_count'), count)
            print(f"✅ Success. {count} symbol records created/updated.")
        else:
            logging.warning("Symbol update returned status: %s", status)
            print(f"⚠️ Warning: Status {status}")

    except (RequestException, PyMongoError, RuntimeError) as e:
        logging.error("Failed to update symbol universe: %s", e)
        print(f"❌ Error: {e}")

def update_history_batch(limit: int = 0, recent_only: bool = True):
    """
    Step 2: Loop through symbols in DB and update their price history.

    Args:
        limit: Max number of symbols to update (0 for all).
        recent_only: If True, fetches 'compact' data (faster, less data).
    """
    print(f"\n--- STEP 2: Updating Price History (Recent Only: {recent_only}) ---")

    # 1. Get all symbols from Mongo
    all_symbols = symbols.get_symbols_from_mongo()

    if limit > 0:
        all_symbols = all_symbols[:limit]
        print(f"Limit applied: Updating first {limit} symbols only.")

    print(f"Found {len(all_symbols)} symbols in database. Starting batch update...")

    # Dynamic rate limit logging
    current_cps = getattr(symbols, 'CPS', 'Unknown')
    print(f"Note: Rate limiting is active ({current_cps} calls/sec). This may take a while.")

    success_count = 0
    error_count = 0

    # tqdm provides a nice progress bar
    pbar = tqdm(all_symbols, unit="ticker")

    for sym_doc in pbar:
        ticker = sym_doc.get("symbol")
        pbar.set_description(f"Processing {ticker}")

        try:
            # This function already has the @limits decorator for rate limiting
            symbols.refresh_historical_for_symbol(ticker, recent=recent_only)
            success_count += 1

        except (RequestException, PyMongoError, RuntimeError, ValueError) as e:
            error_count += 1
            logging.error("Failed to update %s: %s", ticker, str(e))
            # Don't crash the whole batch on one failure
            continue

    print("\n✅ Batch Complete.")
    print(f"Success: {success_count}")
    print(f"Errors:  {error_count}")

def update_overviews_batch(limit: int = 0):
    """
    Step 3: Update company overview data for symbols in DB.
    """
    print("\n--- STEP 3: Updating Company Overviews ---")
    all_symbols = symbols.get_symbols_from_mongo()
    if limit > 0:
        all_symbols = all_symbols[:limit]

    print(f"Found {len(all_symbols)} symbols. Starting overview update...")
    success_count = 0
    error_count = 0
    pbar = tqdm(all_symbols, unit="ticker")

    for sym_doc in pbar:
        ticker = sym_doc.get("symbol")
        pbar.set_description(f"Processing {ticker}")
        try:
            overview = symbols.fetch_overview_from_net(ticker)
            if overview:
                symbols.upsert_overview_to_mongo(ticker, overview)
                success_count += 1
        except (RequestException, PyMongoError, RuntimeError) as e:
            error_count += 1
            logging.error("Failed to update overview for %s: %s", ticker, str(e))
            continue

    print(f"\n✅ Overviews Complete. Success: {success_count}, Errors: {error_count}")

def update_news_batch(limit: int = 0):
    """
    Step 4: Update news sentiment data for symbols in DB.
    """
    print("\n--- STEP 4: Updating News Sentiment ---")
    all_symbols = symbols.get_symbols_from_mongo()
    if limit > 0:
        all_symbols = all_symbols[:limit]

    print(f"Found {len(all_symbols)} symbols. Starting news update...")
    success_count = 0
    error_count = 0
    pbar = tqdm(all_symbols, unit="ticker")

    for sym_doc in pbar:
        ticker = sym_doc.get("symbol")
        pbar.set_description(f"Processing {ticker}")
        try:
            news = symbols.fetch_news_sentiment_from_net(ticker)
            if news:
                symbols.upsert_news_sentiment_to_mongo(ticker, news)
                success_count += 1
        except (RequestException, PyMongoError, RuntimeError) as e:
            error_count += 1
            logging.error("Failed to update news for %s: %s", ticker, str(e))
            continue

    print(f"\n✅ News Complete. Success: {success_count}, Errors: {error_count}")

def retrain_ml_models(limit: int = 10000):
    """
    Step 5: Retrain ML Overlay models using newly graded trades.
    """
    print("\n--- STEP 5: Retraining ML Models ---")
    try:
        trainer = MLOverlayTrainer()
        trainer.retrain_all(limit=limit)
        print("✅ Retraining Complete.")
    except Exception as e:  # pylint: disable=broad-exception-caught
        logging.error("Failed to retrain ML models: %s", e)
        print(f"❌ Error: {e}")

def main():
    """Main entry point for maintenance script."""
    parser = argparse.ArgumentParser(description="BlueHorseshoe Data Maintenance")

    parser.add_argument("--symbols", action="store_true", help="Update the list of active symbols from AlphaVantage")
    parser.add_argument("--history", action="store_true", help="Update OHLC price history for symbols in DB")
    parser.add_argument("--overviews", action="store_true", help="Update company overview data (Sector, Industry, etc.)")
    parser.add_argument("--news", action="store_true", help="Update news sentiment data")
    parser.add_argument("--retrain", action="store_true", help="Retrain ML models using graded trades")
    parser.add_argument("--full", action="store_true", help="Run symbols, history, overviews, news updates, and retrain models")
    parser.add_argument("--limit", type=int, default=0, help="Limit update to N symbols (for testing)")
    parser.add_argument("--deep", action="store_true", help="Fetch FULL history instead of compact (recent)")

    args = parser.parse_args()

    # Ensure DB connection
    db.connect()

    if args.symbols or args.full:
        update_symbol_universe()

    if args.history or args.full:
        # Default to recent=True unless --deep is passed
        recent_mode = not args.deep
        update_history_batch(limit=args.limit, recent_only=recent_mode)

    if args.overviews or args.full:
        update_overviews_batch(limit=args.limit)

    if args.news or args.full:
        update_news_batch(limit=args.limit)

    if args.retrain or args.full:
        # For ML training, 0 limit usually means "use a reasonable default" in prepare_training_data
        # We'll use 10000 as a default if limit is 0
        train_limit = args.limit if args.limit > 0 else 10000
        retrain_ml_models(limit=train_limit)

    if not (args.symbols or args.history or args.overviews or args.news or args.retrain or args.full):
        parser.print_help()

if __name__ == "__main__":
    main()
