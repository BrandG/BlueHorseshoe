import sys
import os
import logging
from datetime import datetime, timedelta
import pandas as pd

# Ensure src is in PYTHONPATH
sys.path.append('/workspaces/BlueHorseshoe/src')

from bluehorseshoe.analysis.strategy import SwingTrader
from bluehorseshoe.core.scores import score_manager
from bluehorseshoe.core.globals import get_mongo_client

def rebuild_scores(start_date: str, end_date: str, inverted: bool = False, symbols: list[str] = None):
    """
    Rebuilds scores for a range of dates.
    """
    trader = SwingTrader()

    start = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')

    current = start
    while current <= end:
        # Skip weekends
        if current.weekday() < 5:
            date_str = current.strftime('%Y-%m-%d')
            print(f"\nRebuilding scores for {date_str}...")
            trader.swing_predict(target_date=date_str, symbols=symbols)
        current += timedelta(days=1)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 3:
        print("Usage: python src/rebuild_scores.py <start_date> <end_date> [--inverted] [--symbols=A,AAPL]")
        sys.exit(1)

    start_dt = sys.argv[1]
    end_dt = sys.argv[2]
    is_inverted = "--inverted" in sys.argv

    # Parse symbols if provided
    symbols_filter = None
    for arg in sys.argv:
        if arg.startswith("--symbols="):
            symbols_filter = arg.split("=")[1].split(",")

    rebuild_scores(start_dt, end_dt, inverted=is_inverted, symbols=symbols_filter)
    print("\nRebuild complete.")
