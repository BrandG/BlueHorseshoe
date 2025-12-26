import argparse
import logging
import time
from datetime import datetime
from tqdm import tqdm  # You might need to pip install tqdm

# Import our internal modules
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
            logging.info(f"Symbol universe updated. Processed {result.get('symbol_count')} symbols. Database changes: {count}")
            print(f"✅ Success. {count} symbol records created/updated.")
        else:
            logging.warning(f"Symbol update returned status: {status}")
            print(f"⚠️ Warning: Status {status}")
            
    except Exception as e:
        logging.error(f"Failed to update symbol universe: {e}")
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
            
        except Exception as e:
            error_count += 1
            logging.error(f"Failed to update {ticker}: {str(e)}")
            # Don't crash the whole batch on one failure
            continue
            
    print(f"\n✅ Batch Complete.")
    print(f"Success: {success_count}")
    print(f"Errors:  {error_count}")

def main():
    parser = argparse.ArgumentParser(description="BlueHorseshoe Data Maintenance")
    
    parser.add_argument("--symbols", action="store_true", help="Update the list of active symbols from AlphaVantage")
    parser.add_argument("--history", action="store_true", help="Update OHLC price history for symbols in DB")
    parser.add_argument("--full", action="store_true", help="Run both symbols and history updates")
    parser.add_argument("--limit", type=int, default=0, help="Limit history update to N symbols (for testing)")
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

    if not (args.symbols or args.history or args.full):
        parser.print_help()

if __name__ == "__main__":
    main()