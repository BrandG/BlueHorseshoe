"""
Script to check for missing historical price data.
"""
import logging
import sys
import os
from datetime import datetime

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'src'))

# pylint: disable=wrong-import-position
from bluehorseshoe.core.globals import get_mongo_client
from bluehorseshoe.core.symbols import get_symbol_list

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

def check_completeness():
    db = get_mongo_client()
    if db is None:
        logging.error("Could not connect to MongoDB")
        sys.exit(1)

    col = db['historical_prices']

    logging.info("Fetching symbol list...")
    symbols = get_symbol_list()
    logging.info("Found %d total symbols.", len(symbols))

    incomplete_symbols = []
    missing_symbols = []

    # We can optimize this by fetching all existing symbols in one go, but let's do one-by-one for detailed checks first
    # Or better, fetch a projection of symbol, min_date, and count

    logging.info("Checking historical data completeness...")

    # Use aggregation to get stats for all symbols in historical_prices
    pipeline = [
        {
            "$project": {
                "symbol": 1,
                "count": {"$size": "$days"},
                "first_date": {"$arrayElemAt": ["$days.date", 0]},
                "last_date": {"$arrayElemAt": ["$days.date", -1]}
            }
        }
    ]

    # Create a map of existing data stats
    existing_stats = {}
    cursor = col.aggregate(pipeline)
    for doc in cursor:
        existing_stats[doc['symbol']] = doc

    logging.info("Found historical data for %d symbols.", len(existing_stats))

    cutoff_date = "2024-01-01"

    for s in symbols:
        sym = s['symbol']
        if sym not in existing_stats:
            missing_symbols.append(sym)
            continue

        stats = existing_stats[sym]
        count = stats.get('count', 0)
        first_date = stats.get('first_date', '9999-99-99')

        # Criteria for incomplete
        if count < 200: # Less than a year roughly
            incomplete_symbols.append(f"{sym} (Count: {count})")
        elif first_date > cutoff_date:
            incomplete_symbols.append(f"{sym} (First Date: {first_date})")

    logging.info("Missing Data: %d", len(missing_symbols))
    logging.info("Incomplete Data: %d", len(incomplete_symbols))

    with open('src/logs/missing_symbols.txt', 'w') as f:
        for s in missing_symbols:
            f.write(f"{s}\n")

    with open('src/logs/incomplete_symbols.txt', 'w') as f:
        for s in incomplete_symbols:
            f.write(f"{s}\n")

    logging.info("Written lists to src/logs/missing_symbols.txt and src/logs/incomplete_symbols.txt")

if __name__ == "__main__":
    check_completeness()
