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
    parser.add_argument('--hold', type=int, default=10, help='Hold period in days')
    parser.add_argument('--save', action='store_true', help='Save grading results to DB')
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

    if args.save:
        from bluehorseshoe.core.database import db
        coll = db.get_db()['trade_scores']
        print(f"Saving results for {len(results)} trades...")
        save_count = 0
        for res in results:
            if res['status'] in ['success', 'failure']:
                # Ensure date is a string YYYY-MM-DD
                d_str = res['date']
                if not isinstance(d_str, str):
                    d_str = d_str.strftime('%Y-%m-%d')
                else:
                    d_str = d_str[:10]

                update_result = coll.update_one(
                    {"symbol": res['symbol'], "date": d_str, "strategy": res['strategy']},
                    {"$set": {
                        "status": res['status'],
                        "pnl": float(res['pnl']),
                        "mae_atr": float(res.get('mae_atr', 0.0)),
                        "exit_price": float(res['exit_price']),
                        "exit_date": res['exit_date'],
                        "max_gain": float(res.get('max_gain', 0.0))
                    }}
                )
                if update_result.modified_count > 0 or update_result.upserted_id:
                    save_count += 1
        print(f"Save complete. Modified/Updated {save_count} documents.")

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
