
import sys
import os
import logging
from bluehorseshoe.data.historical_data import process_symbol

# Mocking logging to see output
logging.basicConfig(level=logging.INFO)

def update_specific():
    symbols_to_update = [
        {'symbol': 'SPY', 'name': 'SPDR S&P 500 ETF Trust'},
        {'symbol': 'QQQ', 'name': 'Invesco QQQ Trust'}
    ]
    
    print("Starting manual update for SPY and QQQ (Full history)...")
    for i, row in enumerate(symbols_to_update):
        # process_symbol(row, index, total_symbols, save_to_file, recent)
        process_symbol(row, i+1, len(symbols_to_update), save_to_file=False, recent=False)
        print(f"Finished {row['symbol']}")

if __name__ == "__main__":
    update_specific()
