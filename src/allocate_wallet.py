import sys
import os
import pandas as pd
from typing import List, Dict, Any
from datetime import datetime

# Ensure src is in PYTHONPATH
sys.path.append('/workspaces/BlueHorseshoe/src')

from bluehorseshoe.core.database import db as database_instance
from bluehorseshoe.core.scores import score_manager
from bluehorseshoe.core.symbols import get_overview_from_mongo
from bluehorseshoe.analysis.market_regime import MarketRegime
from bluehorseshoe.data.historical_data import load_historical_data

def get_latest_date():
    """Find the most recent date in the trade_scores collection."""
    db = database_instance.get_db()
    latest = db.trade_scores.find_one(sort=[("date", -1)])
    return latest["date"] if latest else None

def get_price(symbol, metadata):
    """Retrieve entry price from metadata or fall back to latest close."""
    price = metadata.get("entry_price")
    if price and price > 0:
        return price
    
    # Fallback to historical data
    data = load_historical_data(symbol)
    if data and data.get('days'):
        return data['days'][-1]['close']
    return 0

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

    # 2. Market Regime Check
    health = MarketRegime.get_market_health()
    print(f"\nMARKET HEALTH: {health['status']} (Multiplier: {health['multiplier']:.2f})")
    
    original_balance = wallet_balance
    wallet_balance *= health['multiplier']
    
    if wallet_balance == 0:
        print("\n!!! MARKET IS BEARISH: CIRCUIT BREAKER ACTIVE (0% ALLOCATION) !!!")
        print(f"Recommended Action: Stay in Cash. (Original Wallet: ${original_balance:,.2f})")
    elif health['multiplier'] < 1.0:
        print(f"\n!!! MARKET IS NEUTRAL: REDUCING POSITION SIZES BY {(1-health['multiplier'])*100:.0f}% !!!")
        print(f"Effective Trading Balance: ${wallet_balance:,.2f}")

    # 3. Fetch Latest Scores
    latest_date = get_latest_date()
    if not latest_date:
        print("\nError: No scores found in database. Run 'python src/main.py -p' first.")
        return

    print(f"\nUsing latest analysis from: {latest_date}")
    
    baseline_candidates = score_manager.get_scores(latest_date, strategy="baseline")
    mr_candidates = score_manager.get_scores(latest_date, strategy="mean_reversion")
    
    # Filter for candidates with scores high enough to matter
    # Baseline threshold: 16 (matches allocate_wallet logic)
    # MR threshold: 8 (most MR scores are lower)
    top_baseline = [s for s in baseline_candidates if s["score"] >= 16][:5]
    top_mr = [s for s in mr_candidates if s["score"] >= 8][:5]
    
    results = []
    
    # Process Baseline
    for s in top_baseline:
        meta = s.get("metadata", {})
        price = get_price(s["symbol"], meta)
        results.append({
            "symbol": s["symbol"],
            "strategy": "Baseline",
            "score": s["score"],
            "weight": max(1.0, float(s["score"] - 15)),
            "price": price,
            "sector": "Unknown"
        })
        
    # Process Mean Reversion
    for s in top_mr:
        meta = s.get("metadata", {})
        price = get_price(s["symbol"], meta)
        results.append({
            "symbol": s["symbol"],
            "strategy": "Dip-Buy",
            "score": s["score"],
            "weight": max(1.0, float(s["score"] - 5)),
            "price": price,
            "sector": "Unknown"
        })

    if not results:
        print("\nNo eligible candidates found.")
        return

    # 4. Attach Sectors
    for res in results:
        ov = get_overview_from_mongo(res['symbol'])
        if ov:
            res['sector'] = ov.get('Sector', 'Unknown')

    # 5. Calculate Allocations
    total_weight = sum(r['weight'] for r in results)
    unit_allocation = wallet_balance / total_weight if total_weight > 0 else 0

    print(f"\nFound {len(results)} suggestions ({len(top_baseline)} Baseline, {len(top_mr)} Dip-Buy).")
    print("-" * 105)
    print(f"{ 'STRATEGY':<10} | {'SYMBOL':<8} | {'SCORE':<6} | {'WEIGHT':<6} | {'ALLOCATION':<12} | {'PRICE':<8} | {'SHARES':<6} | {'SECTOR':<20}")
    print("-" * 105)

    for res in results:
        allocation = unit_allocation * res['weight']
        price = res['price']
        shares = int(allocation / price) if price > 0 else 0
        print(f"{res['strategy']:<10} | {res['symbol']:<8} | {res['score']:<6.1f} | {res['weight']:<6.2f} | ${allocation:<11,.2f} | ${price:<8.2f} | {shares:<6} | {res['sector']:<20}")

    print("-" * 105)
    print(f"TRADING WALLET: ${wallet_balance:,.2f} (from ${original_balance:,.2f} total)")
    print("==========================================")

if __name__ == "__main__":
    # Suppress redundant logging
    import logging
    logging.getLogger().setLevel(logging.ERROR)
    main()
