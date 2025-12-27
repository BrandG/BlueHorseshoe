import sys
import os
import pandas as pd
from typing import List, Dict

# Ensure src is in PYTHONPATH
sys.path.append('/workspaces/BlueHorseshoe/src')

from bluehorseshoe.analysis.strategy import SwingTrader
from bluehorseshoe.analysis.market_regime import MarketRegime
from bluehorseshoe.core.symbols import (
    get_symbol_name_list, 
    get_overview_from_mongo, 
    fetch_overview_from_net, 
    upsert_overview_to_mongo
)
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

    # 1.5 Market Regime Check
    health = MarketRegime.get_market_health()
    print(f"\nMARKET HEALTH: {health['status']} (Multiplier: {health['multiplier']:.2f})")
    for sym, details in health['details'].items():
        if isinstance(details, dict):
            print(f" - {sym}: {'Bullish' if details['bullish'] else 'Bearish'} ({details['trend']})")
    
    original_balance = wallet_balance
    wallet_balance *= health['multiplier']
    
    if wallet_balance == 0:
        print("\n!!! MARKET IS BEARISH: CIRCUIT BREAKER ACTIVE (0% ALLOCATION) !!!")
        print(f"Recommended Action: Stay in Cash. (Original Wallet: ${original_balance:,.2f})")
        # We'll continue to show what WOULD be bought, but with 0 allocation
    elif health['multiplier'] < 1.0:
        print(f"\n!!! MARKET IS NEUTRAL: REDUCING POSITION SIZES BY {(1-health['multiplier'])*100:.0f}% !!!")
        print(f"Effective Trading Balance: ${wallet_balance:,.2f}")

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

    # 2.5 Filter by Market Cap and attach Sector
    print(f"\nProcessing metadata for {len(results)} candidates...")
    filtered_results = []
    
    # We do this sequentially because of Alpha Vantage rate limits if we have to fetch from net
    for res in results:
        ov = get_overview_from_mongo(res['symbol'])
        if not ov:
            # Only fetch if we really have to, and respect rate limits
            try:
                ov = fetch_overview_from_net(res['symbol'])
                if ov:
                    upsert_overview_to_mongo(res['symbol'], ov)
            except Exception:
                pass
        
        if ov:
            res['sector'] = ov.get('Sector', 'Unknown')
            try:
                mcap = float(ov.get('MarketCapitalization', 0))
                res['market_cap'] = mcap
            except (ValueError, TypeError):
                res['market_cap'] = 0
        else:
            res['sector'] = 'Unknown'
            res['market_cap'] = 0
            
        # Filter: Market Cap > 500M (Default)
        MIN_MCAP = 500_000_000
        if res['market_cap'] >= MIN_MCAP:
            filtered_results.append(res)
        else:
            # Skipping low cap or unknown
            pass

    print(f"Filtered down to {len(filtered_results)} stocks with Market Cap >= ${MIN_MCAP/1e6:.0f}M")
    results = filtered_results

    if not results:
        print("\nNo candidates passed the Market Cap filter.")
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

    # 4. Calculate Tiered Allocation with Sector Diversification
    # Formula: weight = score - 15
    for res in results:
        res['weight'] = float(max(1, int(res['score'] - 15)))

    def calculate_allocations(current_results, balance):
        tw = sum(r['weight'] for r in current_results)
        if tw == 0: return 0, 0
        ua = balance / tw
        return tw, ua

    total_weight, unit_allocation = calculate_allocations(results, wallet_balance)

    # Sector Diversification: Max 30% per sector
    MAX_SECTOR_PCT = 0.30
    MAX_SECTOR_VAL = wallet_balance * MAX_SECTOR_PCT
    
    sector_totals = {}
    for res in results:
        sector = res['sector']
        alloc = res['weight'] * unit_allocation
        sector_totals[sector] = sector_totals.get(sector, 0) + alloc

    needs_scaling = False
    for sector, total in sector_totals.items():
        if total > MAX_SECTOR_VAL:
            needs_scaling = True
            ratio = MAX_SECTOR_VAL / total
            for res in results:
                if res['sector'] == sector:
                    res['weight'] *= ratio

    if needs_scaling:
        total_weight, unit_allocation = calculate_allocations(results, wallet_balance)

    print(f"\n\nFound {len(results)} eligible trades (Score >= 16) after Market Cap filter.")
    print(f"Total Portfolio Weight: {total_weight:.2f}")
    if needs_scaling:
        print("Note: Sector diversification limits applied (max 30% per sector).")
    print("-" * 85)
    print(f"{'SYMBOL':<8} | {'SCORE':<6} | {'WEIGHT':<6} | {'ALLOCATION':<12} | {'PRICE':<8} | {'SECTOR':<20}")
    print("-" * 85)

    for res in results[:20]: # Show top 20
        allocation = unit_allocation * res['weight']
        print(f"{res['symbol']:<8} | {res['score']:<6.1f} | {res['weight']:<6.2f} | ${allocation:<11,.2f} | ${res['entry_price']:<8.2f} | {res['sector']:<20}")

    if len(results) > 20:
        print(f"... and {len(results) - 20} more candidates.")

    print("-" * 85)
    print(f"TRADING WALLET: ${wallet_balance:,.2f} (from ${original_balance:,.2f} total)")
    print("==========================================")

if __name__ == "__main__":
    # Suppress redundant logging
    import logging
    logging.getLogger().setLevel(logging.ERROR)
    main()
