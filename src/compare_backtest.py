"""
Mini-backtest: Compare V2 vs V3 baseline top picks for 2025-10-01.
Loads actual price data for the hold period and simulates outcomes.
"""
import sys
import json
sys.path.insert(0, 'src')

import pandas as pd
import numpy as np
from pymongo import MongoClient

TARGET_DATE = "2025-10-01"
HOLD_DAYS = 10
TARGET_PCT = 0.01   # 1% target
STOP_PCT = 0.02     # 2% stop

# Get all symbols with enough data
client = MongoClient('mongodb://mongo:27017')
db = client['bluehorseshoe']

from bluehorseshoe.core.config import weights_config
from bluehorseshoe.analysis.technical_analyzer import TechnicalAnalyzer
from bluehorseshoe.analysis.constants import MIN_STOCK_PRICE, MAX_STOCK_PRICE, MIN_VOLUME_THRESHOLD


def load_symbol_data(symbol):
    """Load full data for a symbol."""
    doc = db.historical_prices_recent.find_one({"symbol": symbol})
    if not doc or not doc.get('days'):
        doc = db.historical_prices.find_one({"symbol": symbol})
    if not doc or not doc.get('days'):
        return None
    df = pd.DataFrame(doc['days'])
    if 'date' not in df.columns:
        return None
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    return df


def score_symbol(df, target_date):
    """Score a symbol for a target date, return baseline score or None."""
    scoring_data = df[df['date'] <= target_date].copy()
    if len(scoring_data) < 60:
        return None

    last = scoring_data.iloc[-1]

    # Price filter
    price = last['close']
    if price < MIN_STOCK_PRICE or price > MAX_STOCK_PRICE:
        return None

    # Volume filter
    avg_vol = last.get('avg_volume_20', 0)
    if avg_vol < MIN_VOLUME_THRESHOLD:
        return None

    result = TechnicalAnalyzer.calculate_baseline_score(scoring_data)
    return result.get('total', 0.0)


def simulate_trade(df, target_date, hold_days=10, target_pct=0.01, stop_pct=0.02):
    """Simulate a trade entry day after target date."""
    future_data = df[df['date'] > target_date].head(hold_days + 1)
    if len(future_data) < 2:
        return None

    # Entry at next day's open
    entry_price = future_data.iloc[0]['open']
    if entry_price <= 0:
        return None

    target_price = entry_price * (1 + target_pct)
    stop_price = entry_price * (1 - stop_pct)

    for i in range(len(future_data)):
        row = future_data.iloc[i]
        # Check stop first (conservative)
        if row['low'] <= stop_price:
            return {
                'entry': entry_price,
                'exit': stop_price,
                'days_held': i,
                'outcome': 'LOSS',
                'pnl': -stop_pct * 100
            }
        # Check target
        if row['high'] >= target_price:
            return {
                'entry': entry_price,
                'exit': target_price,
                'days_held': i,
                'outcome': 'WIN',
                'pnl': target_pct * 100
            }

    # Hold period expired - close at last close
    exit_price = future_data.iloc[-1]['close']
    pnl = (exit_price / entry_price - 1) * 100
    return {
        'entry': entry_price,
        'exit': exit_price,
        'days_held': len(future_data),
        'outcome': 'WIN' if pnl > 0 else 'LOSS',
        'pnl': round(pnl, 2)
    }


def run_comparison(symbols_batch, v2_path, v3_path):
    """Score all symbols with both weight sets and return DataFrames."""
    v2_scores = []
    v3_scores = []

    for i, symbol in enumerate(symbols_batch):
        if i % 100 == 0:
            print(f"  Scoring {i}/{len(symbols_batch)}...")

        df = load_symbol_data(symbol)
        if df is None:
            continue

        # V3 scoring
        with open(v3_path) as f:
            weights_config._weights = json.load(f)
        v3_score = score_symbol(df, TARGET_DATE)

        # V2 scoring
        with open(v2_path) as f:
            weights_config._weights = json.load(f)
        v2_score = score_symbol(df, TARGET_DATE)

        if v3_score is not None:
            v3_scores.append({'symbol': symbol, 'score': v3_score, 'df': df})
        if v2_score is not None:
            v2_scores.append({'symbol': symbol, 'score': v2_score, 'df': df})

    return v2_scores, v3_scores


def backtest_picks(scored_list, top_n=40, label=""):
    """Take top N picks and simulate trades."""
    sorted_picks = sorted(scored_list, key=lambda x: x['score'], reverse=True)[:top_n]

    results = []
    for pick in sorted_picks:
        trade = simulate_trade(pick['df'], TARGET_DATE, HOLD_DAYS, TARGET_PCT, STOP_PCT)
        if trade:
            trade['symbol'] = pick['symbol']
            trade['score'] = pick['score']
            results.append(trade)

    if not results:
        print(f"\n{label}: No trades executed")
        return

    wins = [r for r in results if r['outcome'] == 'WIN']
    losses = [r for r in results if r['outcome'] == 'LOSS']
    total_pnl = sum(r['pnl'] for r in results)
    avg_pnl = total_pnl / len(results)

    print(f"\n{'='*70}")
    print(f"{label} — Top {top_n} picks backtest ({TARGET_DATE}, {HOLD_DAYS}d hold)")
    print(f"{'='*70}")
    print(f"Trades: {len(results)} | Wins: {len(wins)} | Losses: {len(losses)}")
    print(f"Win Rate: {len(wins)/len(results)*100:.1f}%")
    print(f"Total P&L: {total_pnl:+.2f}%")
    print(f"Avg P&L: {avg_pnl:+.2f}%")
    print(f"Avg Win: {np.mean([r['pnl'] for r in wins]):+.2f}%" if wins else "  No wins")
    print(f"Avg Loss: {np.mean([r['pnl'] for r in losses]):+.2f}%" if losses else "  No losses")

    print(f"\nDetailed trades (sorted by score):")
    for r in sorted(results, key=lambda x: x['score'], reverse=True):
        print(f"  {r['symbol']:8s} score={r['score']:>6.1f} entry={r['entry']:>8.2f} "
              f"exit={r['exit']:>8.2f} held={r['days_held']}d {r['outcome']:>4s} pnl={r['pnl']:>+6.2f}%")

    return results


def main():
    v3_path = '/workspaces/BlueHorseshoe/src/weights.json'
    v2_path = '/workspaces/BlueHorseshoe/src/weights_v2.json'

    # Get a good sample of liquid symbols
    # Use the symbols from the NASDAQ list
    # Get symbols directly from MongoDB
    all_symbols = sorted(db.historical_prices_recent.distinct('symbol'))
    if not all_symbols:
        all_symbols = sorted(db.historical_prices.distinct('symbol'))
    print(f"Total symbols: {len(all_symbols)}")

    # Score a manageable subset - take every Nth symbol for speed
    # Plus ensure we include the V3 backtest picks
    v3_known = ['KT','TRNO','DOO','VNO','AER','COKE','E','ROG','BLDR','KLIC',
                'MKC','STAG','EIM','PSX','STZ','DUHP','ACWX','LXP','VLO',
                'SCHX','HFXI','IWB','SPYG','SHC','FDD','LKQ','MORT',
                'MTRN','RA','JIRE','WPC','EWH','PAG','RYLD']

    # Sample: every 10th symbol + known picks (gives ~640 + 34 = ~670 symbols)
    sample = list(set(all_symbols[::10] + v3_known))
    print(f"Scoring {len(sample)} symbols with both V2 and V3 weights...")

    v2_scores, v3_scores = run_comparison(sample, v2_path, v3_path)
    print(f"V2 scored: {len(v2_scores)} symbols")
    print(f"V3 scored: {len(v3_scores)} symbols")

    # Backtest top 40 from each
    v2_results = backtest_picks(v2_scores, top_n=40, label="V2 WEIGHTS")
    v3_results = backtest_picks(v3_scores, top_n=40, label="V3 WEIGHTS")

    # Overlap
    if v2_results and v3_results:
        v2_syms = {r['symbol'] for r in v2_results}
        v3_syms = {r['symbol'] for r in v3_results}
        overlap = v2_syms & v3_syms
        print(f"\n--- PICK OVERLAP ---")
        print(f"V2 picks: {len(v2_syms)}")
        print(f"V3 picks: {len(v3_syms)}")
        print(f"Overlap: {len(overlap)} ({len(overlap)/max(len(v2_syms),len(v3_syms))*100:.0f}%)")
        print(f"Shared: {sorted(overlap)}")

    # Restore V3
    with open(v3_path) as f:
        weights_config._weights = json.load(f)


if __name__ == '__main__':
    main()
