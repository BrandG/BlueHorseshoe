import sys
import os
import logging
import pandas as pd
import argparse

# Ensure src is in PYTHONPATH
sys.path.append('/workspaces/BlueHorseshoe/src')

from bluehorseshoe.analysis.grading_engine import GradingEngine

def main():
    parser = argparse.ArgumentParser(description='Run Grading Engine')
    parser.add_argument('--limit', type=int, default=5000, help='Max scores to grade')
    parser.add_argument('--strategy', type=str, help='Filter by strategy name')
    parser.add_argument('--hold', type=int, default=10, help='Holding period in days')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(message)s')
    
    engine = GradingEngine(hold_days=args.hold)
    
    query = {"metadata.entry_price": {"$exists": True}}
    if args.strategy:
        query["strategy"] = args.strategy
        print(f"Filtering by strategy: {args.strategy}")

    print(f"Fetching up to {args.limit} scores and evaluating performance...")
    results = engine.run_grading(query=query, limit=args.limit)
    
    if not results:
        print("No results found.")
        return
        
    summary = engine.summarize_results(results)
    comp_summary = engine.summarize_components(results)
    
    if summary.empty:
        print("Could not generate summary (likely no valid trades found).")
        return
        
    print("\nPerformance Summary by Score Tier:")
    print("===================================")
    print(summary.to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    
    if not comp_summary.empty:
        print("\nPerformance Summary by Individual Component:")
        print("===========================================")
        print(comp_summary.to_string(index=False, float_format=lambda x: f"{x:.2f}"))

    # Also print overall stats
    df = pd.DataFrame(results)
    df = df[df['status'].isin(['success', 'failure'])]
    if not df.empty:
        overall_win_rate = (df['status'] == 'success').mean() * 100
        overall_pnl = df['pnl'].mean()
        print("\nOverall Performance:")
        print(f"Total Trades: {len(df)}")
        print(f"Win Rate:     {overall_win_rate:.2f}%")
        print(f"Avg PnL:      {overall_pnl:.2f}%")

if __name__ == "__main__":
    main()
