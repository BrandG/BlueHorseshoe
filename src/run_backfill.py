
"""
Script to run backfill for incomplete symbols.
"""
import logging
import sys
import os
import argparse

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'src'))

# pylint: disable=wrong-import-position
from bluehorseshoe.data.historical_data import build_all_symbols_history
from bluehorseshoe.core.globals import get_mongo_client

def main():
    parser = argparse.ArgumentParser(description='Backfill historical data for incomplete symbols.')
    parser.add_argument('--limit', type=int, default=50, help='Number of symbols to process')
    parser.add_argument('--file', type=str, default='src/logs/incomplete_symbols.txt', help='Path to incomplete symbols list')
    args = parser.parse_args()

    # Configure logging to stdout
    root = logging.getLogger()
    if root.handlers:
        for handler in root.handlers:
            root.removeHandler(handler)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s', handlers=[logging.StreamHandler(sys.stdout)])

    if not os.path.exists(args.file):
        logging.error(f"File {args.file} not found.")
        sys.exit(1)

    symbols_to_process = []
    with open(args.file, 'r') as f:
        content = f.read()
        # Handle both newlines and spaces
        tokens = content.replace('\n', ' ').split(' ')

    # Parse symbols
    for token in tokens:
        sym = token.strip()
        if sym and sym.isalnum():
            symbols_to_process.append({'symbol': sym, 'name': sym})


    if not symbols_to_process:
        logging.info("No symbols found to process.")
        return

    # Apply limit
    batch = symbols_to_process[:args.limit]
    logging.info(f"Starting backfill for {len(batch)} symbols (Limit: {args.limit})...")

    # Run backfill
    # We set recent=False to force 'full' outputsize
    build_all_symbols_history(symbols=batch, recent=False)

    logging.info("Batch complete.")

    # Optional: Update the file (remove processed)
    # For now, we won't auto-modify the input file to avoid data loss if it fails mid-way,
    # but in a robust system we would mark them as done.

if __name__ == "__main__":
    main()
