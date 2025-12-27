import sys
import os
import pandas as pd
from typing import List, Dict

# Ensure src is in PYTHONPATH
sys.path.append('/workspaces/BlueHorseshoe/src')

from bluehorseshoe.analysis.strategy import SwingTrader
from bluehorseshoe.core.symbols import get_symbol_name_list
from bluehorseshoe.core.globals import get_mongo_client, GlobalData

def main():
    print("==========================================")
    print(" BLUE HORSESHOE: TIERED ALLOCATION TOOL")
    print("==========================================")

    # 1. Get Wallet Amount
    wallet_balance = None
    if len(sys.argv) > 1:
        try:
            wallet_balance = float(sys.argv[1].replace(',', ''))
        except ValueError:
            pass

    if wallet_balance is None:
        try:
            wallet_input = input("\nEnter your current wallet balance (e.g., 10000): ")
            wallet_balance = float(wallet_input.replace(',', ''))
        except (ValueError, EOFError):
            print("\nError: Invalid input or non-interactive terminal detected.")
            print("Usage: python src/allocate_wallet.py [wallet_balance]")
            return

    # 2. Run Analysis
    # Set holiday to True to bypass the strict "must be yesterday" check in SwingTrader
    from bluehorseshoe.core.globals import GlobalData
    GlobalData.holiday = True
    
    trader = SwingTrader()
    symbols = get_symbol_name_list()
    
    print(f"\nScanning {len(symbols)} symbols. This may take a moment...")
    
    # Track the latest date found in the data to warn the user
    latest_date_found = None
    
    results = []
    processed = 0
    total = len(symbols)
    
    import concurrent.futures
    from functools import partial
    
    max_workers = min(8, os.cpu_count() or 4)
    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        process_func = partial(trader.process_symbol, target_date=None)
        future_to_symbol = {executor.submit(process_func, sym): sym for sym in symbols}
        
        for future in concurrent.futures.as_completed(future_to_symbol):
            processed += 1
            try:
                res = future.result()
                if res:
                    # Capture the date from the underlying data if possible
                    # (SwingTrader doesn't return the date in res, so we'll just proceed)
                    if res['score'] >= 16:
                        results.append(res)
            except Exception:
                pass
            
            if processed % 100 == 0 or processed == total:
                print(f" Progress: {processed}/{total} symbols analyzed...", end='\r')

    if not results:
        print("\n\nNo eligible trades found (Score >= 16).")
        print("Note: If you haven't updated your data recently, run the update script first.")
        return

    # Check the actual date of the data from a sample
    from bluehorseshoe.data.historical_data import load_historical_data
    sample_data = load_historical_data(results[0]['symbol'])
    if sample_data and 'days' in sample_data and sample_data['days']:
        latest_date_found = sample_data['days'][-1]['date']
        
    print(f"\n\nAnalysis complete based on data as of: {latest_date_found or 'Unknown'}")
    if latest_date_found and latest_date_found < pd.Timestamp.now().normalize().strftime('%Y-%m-%d'):
        print("WARNING: Data is not up to date. Position sizing may be based on stale prices.")

    # 3. Sort by Score
    results = sorted(results, key=lambda x: x['score'], reverse=True)

    # 4. Calculate Tiered Allocation
    # Formula: weight = score - 15
    total_weight = 0
    for res in results:
        res['weight'] = max(1, int(res['score'] - 15))
        total_weight += res['weight']

    print(f"\n\nFound {len(results)} eligible trades (Score >= 16).")
    print(f"Total Portfolio Weight: {total_weight}")
    print("-" * 60)
    print(f"{'SYMBOL':<8} | {'SCORE':<6} | {'WEIGHT':<6} | {'ALLOCATION':<12} | {'PRICE':<8}")
    print("-" * 60)

    unit_allocation = wallet_balance / total_weight
    
    for res in results[:20]: # Show top 20
        allocation = unit_allocation * res['weight']
        print(f"{res['symbol']:<8} | {res['score']:<6.1f} | {res['weight']:<6} | ${allocation:<11,.2f} | ${res['entry_price']:<8.2f}")

    if len(results) > 20:
        print(f"... and {len(results) - 20} more candidates.")

    print("-" * 60)
    print(f"TOTAL WALLET: ${wallet_balance:,.2f}")
    print("==========================================")

if __name__ == "__main__":
    # Suppress redundant logging
    import logging
    logging.getLogger().setLevel(logging.ERROR)
    main()
