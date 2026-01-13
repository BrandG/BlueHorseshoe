"""
Script to check for missing historical price data.
"""
import logging
import sys
import os

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'src'))

# pylint: disable=wrong-import-position
from bluehorseshoe.core.globals import get_mongo_client
from bluehorseshoe.core.symbols import get_symbol_list

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

def _get_existing_stats(col):
    """Fetches stats for all symbols in historical_prices using aggregation."""
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
    cursor = col.aggregate(pipeline)
    return {doc['symbol']: doc for doc in cursor}

def _write_symbol_list(file_path, symbols):
    """Writes a list of symbols to a file with UTF-8 encoding."""
    with open(file_path, 'w', encoding='utf-8') as f:
        for s in symbols:
            f.write(f"{s}\n")

def check_completeness():
    """
    Checks the completeness of historical price data.
    """
    database = get_mongo_client()
    if database is None:
        logging.error("Could not connect to MongoDB")
        sys.exit(1)

    logging.info("Fetching symbol list...")
    symbols = get_symbol_list()
    logging.info("Found %d total symbols.", len(symbols))

    existing_stats = _get_existing_stats(database['historical_prices'])
    logging.info("Found historical data for %d symbols.", len(existing_stats))

    incomplete_symbols = []
    missing_symbols = []
    cutoff_date = "2024-01-01"

    for s in symbols:
        sym = s['symbol']
        if sym not in existing_stats:
            missing_symbols.append(sym)
            continue

        stats = existing_stats[sym]
        count = stats.get('count', 0)
        first_date = stats.get('first_date', '9999-99-99')

        if count < 200: # Less than a year roughly
            incomplete_symbols.append(f"{sym} (Count: {count})")
        elif first_date > cutoff_date:
            incomplete_symbols.append(f"{sym} (First Date: {first_date})")

    logging.info("Missing Data: %d", len(missing_symbols))
    logging.info("Incomplete Data: %d", len(incomplete_symbols))

    _write_symbol_list('src/logs/missing_symbols.txt', missing_symbols)
    _write_symbol_list('src/logs/incomplete_symbols.txt', incomplete_symbols)

    logging.info("Written lists to src/logs/missing_symbols.txt and src/logs/incomplete_symbols.txt")

if __name__ == "__main__":
    check_completeness()
